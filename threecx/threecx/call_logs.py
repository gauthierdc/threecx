"""Écriture des appels 3CX dans le doctype « Call Log » d'ERPNext.

Un même appel peut arriver deux fois : par la journalisation du template CRM (fin d'appel) puis
par la synchro XAPI (toutes les 15 min). On rapproche les deux sur le numéro externe et l'heure de
début, et on ne fait que compléter les champs vides du journal existant.
"""

import datetime
import re
from dataclasses import dataclass, field
from urllib.parse import quote

import frappe
from frappe.utils import add_to_date, convert_utc_to_system_timezone

from threecx.threecx.contacts import find_by_number, linked_parties, number_suffix

# Écart toléré entre l'heure de début vue par le template CRM et par l'historique XAPI.
MATCH_WINDOW_SECONDS = 120

CALL_TYPES = {
	# type 3CX -> (type ERPNext, statut ERPNext)
	"Inbound": ("Incoming", "Completed"),
	"Outbound": ("Outgoing", "Completed"),
	"Missed": ("Incoming", "No Answer"),
	"Notanswered": ("Outgoing", "No Answer"),
}


@dataclass
class Call:
	external_number: str
	threecx_call_type: str
	start: datetime.datetime
	end: datetime.datetime | None = None
	duration: int = 0
	agent: str | None = None
	agent_name: str | None = None
	agent_email: str | None = None
	queue: str | None = None
	contact_name: str | None = None
	entity_type: str | None = None
	entity_id: str | None = None
	transcription: str | None = None
	summary: str | None = None
	sentiment: float | None = None
	recording_url: str | None = None
	recording_id: int | None = None
	cdr_id: str | None = None
	source: str = "CRM"
	extra_links: list = field(default_factory=list)

	@property
	def type(self) -> str:
		return CALL_TYPES[self.threecx_call_type][0]

	@property
	def status(self) -> str:
		return CALL_TYPES[self.threecx_call_type][1]


def utc_to_local(value: datetime.datetime | int | float | str | None) -> datetime.datetime | None:
	"""Millisecondes epoch UTC ou datetime/ISO UTC -> datetime naïf dans le fuseau du système."""
	if value in (None, "", 0, "0"):
		return None
	if isinstance(value, int | float) or (isinstance(value, str) and value.isdigit()):
		value = datetime.datetime.fromtimestamp(int(value) / 1000, tz=datetime.timezone.utc)
	elif isinstance(value, str):
		value = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
	return convert_utc_to_system_timezone(value).replace(tzinfo=None)


DURATION_CLOCK = re.compile(r"(?:(\d+)\.)?(\d+):(\d{1,2}):(\d{1,2})(?:\.\d+)?")
DURATION_ISO = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?)?")


def parse_duration(value: str | None) -> int:
	"""Durée 3CX en secondes : « hh:mm:ss » (journalisation CRM) ou ISO 8601 « PT1M5S » (XAPI)."""
	value = (value or "").strip()
	match = DURATION_CLOCK.fullmatch(value) or DURATION_ISO.fullmatch(value)
	if not value or not match:
		return 0
	days, hours, minutes, seconds = (float(part or 0) for part in match.groups())
	return int(days * 86400 + hours * 3600 + minutes * 60 + seconds)


def upsert_call(call: Call):
	existing = _find_existing(call)
	if existing:
		doc = frappe.get_doc("Call Log", existing)
		if _fill_missing(doc, call):
			doc.save(ignore_permissions=True)
		return doc

	doc = frappe.new_doc("Call Log")
	doc.id = _call_id(call)
	doc.type = call.type
	doc.status = call.status
	doc.medium = None
	if call.type == "Incoming":
		doc.set("from", call.external_number)
		doc.to = call.agent or call.queue
	else:
		doc.set("from", call.agent)
		doc.to = call.external_number
	doc.start_time = call.start
	doc.end_time = call.end or (add_to_date(call.start, seconds=call.duration) if call.duration else None)
	doc.duration = call.duration
	doc.employee_user_id = _agent_user(call)
	if doc.employee_user_id:
		doc.call_received_by = frappe.db.get_value("Employee", {"user_id": doc.employee_user_id})

	for doctype, name in _links(call):
		doc.add_link(doctype, name)
		if doctype == "Customer" and not doc.customer:
			doc.customer = name

	_fill_missing(doc, call)
	doc.insert(ignore_permissions=True)

	# La timeline des fiches trie sur `creation` : on la cale sur l'heure réelle de l'appel
	# (utile pour les appels importés après coup par la synchro).
	frappe.db.set_value("Call Log", doc.name, "creation", call.start, update_modified=False)
	return doc


def _call_id(call: Call) -> str:
	if call.cdr_id:
		return f"3cx-{call.cdr_id}"
	stamp = call.start.strftime("%Y%m%d%H%M%S")
	return f"3cx-{stamp}-{number_suffix(call.external_number, 9) or call.external_number}-{call.agent or ''}"


def _find_existing(call: Call) -> str | None:
	if call.cdr_id and (name := frappe.db.get_value("Call Log", {"threecx_cdr_id": call.cdr_id})):
		return name
	if frappe.db.exists("Call Log", _call_id(call)):
		return _call_id(call)

	suffix = number_suffix(call.external_number, 9)
	if not suffix:
		return None
	number_field = "from" if call.type == "Incoming" else "to"
	candidates = frappe.get_all(
		"Call Log",
		filters={
			"type": call.type,
			number_field: ["like", f"%{suffix}"],
			"start_time": [
				"between",
				[
					add_to_date(call.start, seconds=-MATCH_WINDOW_SECONDS),
					add_to_date(call.start, seconds=MATCH_WINDOW_SECONDS),
				],
			],
			"name": ["like", "3cx-%"],
		},
		fields=["name", "threecx_agent"],
		order_by="start_time asc",
	)
	# Un appel distribué par une file peut être journalisé une fois par agent : on privilégie
	# le journal du même poste.
	for candidate in candidates:
		if not call.agent or not candidate.threecx_agent or candidate.threecx_agent == call.agent:
			return candidate.name
	return None


def _fill_missing(doc, call: Call) -> bool:
	"""Complète les champs vides du journal ; renvoie True si quelque chose a changé."""
	changed = False
	values = {
		"threecx_call_type": call.threecx_call_type,
		"threecx_agent": call.agent,
		"threecx_agent_name": call.agent_name,
		"threecx_queue": call.queue,
		"threecx_contact_name": call.contact_name,
		"threecx_source": call.source,
		"threecx_cdr_id": call.cdr_id,
		"threecx_recording_id": call.recording_id,
		"threecx_recording_url": call.recording_url,
		"threecx_sentiment": call.sentiment,
		"threecx_transcription": call.transcription,
		"summary": call.summary,
	}
	for fieldname, value in values.items():
		if value not in (None, "") and not doc.get(fieldname):
			doc.set(fieldname, value)
			changed = True

	# Les journaux 3CX portent le lien d'écoute ERP (proxy authentifié vers 3CX) quand l'ID
	# d'enregistrement est connu, sinon l'URL brute transmise par 3CX.
	if doc.threecx_recording_id:
		recording_url = (
			f"/api/method/threecx.api.desk.recording?call_log={quote(doc.name or doc.id, safe='')}"
		)
	else:
		recording_url = doc.recording_url or doc.threecx_recording_url
	if recording_url != doc.recording_url:
		doc.recording_url = recording_url
		changed = True
	return changed


def _links(call: Call) -> list[tuple[str, str]]:
	if (
		call.entity_type in ("Contact", "Lead")
		and call.entity_id
		and frappe.db.exists(call.entity_type, call.entity_id)
	):
		matches = [{"type": call.entity_type, "id": call.entity_id}]
	else:
		matches = find_by_number(call.external_number)[:3]

	links = []
	for match in matches:
		links.append((match["type"], match["id"]))
		if match["type"] == "Contact":
			links += linked_parties(match["id"])
	return list(dict.fromkeys(links + call.extra_links))


def _agent_user(call: Call) -> str | None:
	if call.agent_email and frappe.db.exists("User", call.agent_email):
		return call.agent_email
	if call.agent:
		return frappe.db.get_value("User", {"threecx_extension": call.agent, "enabled": 1})
	return None
