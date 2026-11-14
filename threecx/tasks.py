"""Synchronisation périodique du journal d'appels 3CX (API de configuration XAPI, V20 Enterprise)."""

import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_datetime, get_system_timezone, now_datetime

from threecx.threecx.call_logs import Call, parse_duration, upsert_call, utc_to_local
from threecx.threecx.client import ThreeCXClient

# Les transcriptions et résumés sont calculés par 3CX après l'appel : on relit une fenêtre
# déjà synchronisée pour les récupérer (les journaux existants sont seulement complétés).
OVERLAP = datetime.timedelta(hours=2)


def sync_call_history(manual: bool = False) -> dict:
	settings = frappe.get_cached_doc("ThreeCX Settings")
	if not manual and not (settings.enabled and settings.xapi_sync_enabled):
		return {}

	period_to = datetime.datetime.now(datetime.timezone.utc)
	if settings.last_sync:
		local = get_datetime(settings.last_sync).replace(tzinfo=ZoneInfo(get_system_timezone()))
		period_from = local.astimezone(datetime.timezone.utc) - OVERLAP
	else:
		period_from = period_to - datetime.timedelta(hours=settings.sync_lookback_hours or 24)

	stats = {"rows": 0, "synced": 0, "skipped": 0, "errors": 0}
	rows = ThreeCXClient().call_log(period_from, period_to)
	stats["rows"] = len(rows)
	for row in rows:
		try:
			call = call_from_xapi(row)
			if not call:
				stats["skipped"] += 1
				continue
			upsert_call(call)
			stats["synced"] += 1
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			stats["errors"] += 1
			frappe.log_error(title="Synchro 3CX : ligne ignorée", message=frappe.as_json(row))

	frappe.db.set_single_value("ThreeCX Settings", "last_sync", now_datetime())
	frappe.db.commit()
	return stats


def call_from_xapi(row: dict) -> Call | None:
	"""Ligne du rapport XAPI « ReportCallLogData » -> appel, ou None pour un appel interne."""
	if row.get("Indent"):
		# Sous-ligne d'un appel (transfert, file d'attente…) : l'appel principal la porte déjà.
		return None

	direction = (row.get("Direction") or "").lower()
	answered = bool(row.get("Answered"))
	if "inbound" in direction:
		call_type = "Inbound" if answered else "Missed"
		external, agent, agent_name, contact_name = (
			row.get("SourceCallerId"),
			row.get("DestinationDn"),
			row.get("DestinationDisplayName"),
			row.get("SourceDisplayName"),
		)
	elif "outbound" in direction:
		call_type = "Outbound" if answered else "Notanswered"
		external, agent, agent_name, contact_name = (
			row.get("DestinationCallerId"),
			row.get("SourceDn"),
			row.get("SourceDisplayName"),
			row.get("DestinationDisplayName"),
		)
	else:
		return None

	start = utc_to_local(row.get("StartTime"))
	if not external or not start:
		return None

	recording = next((r for r in row.get("Recordings") or [] if r.get("Id")), {})
	return Call(
		external_number=external,
		threecx_call_type=call_type,
		start=start,
		duration=parse_duration(row.get("TalkingDuration")),
		agent=agent,
		agent_name=agent_name,
		contact_name=contact_name,
		transcription=row.get("Transcription") or recording.get("Transcription"),
		summary=row.get("Summary") or recording.get("Summary"),
		sentiment=row.get("SentimentScore") or recording.get("SentimentScore"),
		recording_url=row.get("RecordingUrl"),
		recording_id=recording.get("Id") or row.get("DstRecId") or row.get("SrcRecId"),
		# Les segments d'un même appel partagent MainCallHistoryId : un seul journal par appel.
		cdr_id=row.get("MainCallHistoryId") or row.get("CallHistoryId") or row.get("CdrId"),
		source="XAPI",
	)
