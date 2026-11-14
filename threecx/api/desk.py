"""Méthodes appelées depuis le Desk (click-to-call, enregistrements, paramètres)."""

import frappe

from threecx.threecx.client import ThreeCXClient, ThreeCXError

AUDIO_EXTENSIONS = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/ogg": "ogg"}


def _client() -> ThreeCXClient:
	try:
		return ThreeCXClient()
	except ThreeCXError as e:
		frappe.throw(str(e))


def _call_log(name: str):
	doc = frappe.get_doc("Call Log", name)
	doc.check_permission("read")
	if not doc.threecx_recording_id:
		frappe.throw("Aucun enregistrement 3CX n'est associé à cet appel.")
	return doc


# --- Click-to-call -------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def make_call(number: str):
	settings = frappe.get_cached_doc("ThreeCX Settings")
	if not settings.enabled or settings.click_to_call_mode != "API Call Control":
		frappe.throw("Le click-to-call par API 3CX n'est pas activé.")

	extension = frappe.db.get_value("User", frappe.session.user, "threecx_extension")
	if not extension:
		frappe.throw("Renseignez votre poste 3CX dans votre fiche Utilisateur pour passer des appels.")

	try:
		result = _client().make_call(extension, number, settings.call_timeout or 30)
	except ThreeCXError as e:
		frappe.throw(f"3CX n'a pas pu lancer l'appel : {e}")
	return {"extension": extension, "status": result.get("finalstatus"), "reason": result.get("reasontext")}


# --- Enregistrements et transcriptions ------------------------------------------------


@frappe.whitelist()
def recording(call_log: str):
	"""Relaie l'enregistrement 3CX : l'utilisateur ERP l'écoute sans compte 3CX."""
	doc = _call_log(call_log)
	try:
		response = _client().download_recording(doc.threecx_recording_id)
	except ThreeCXError as e:
		frappe.throw(str(e))

	content_type = response.headers.get("Content-Type", "audio/wav").split(";")[0]
	frappe.local.response.update(
		{
			"type": "binary",
			"filename": f"{doc.name}.{AUDIO_EXTENSIONS.get(content_type, 'wav')}",
			"filecontent": response.content,
			"display_content_as": "inline",
		}
	)


@frappe.whitelist(methods=["POST"])
def request_transcription(call_log: str):
	doc = _call_log(call_log)
	try:
		_client().transcribe_recordings([doc.threecx_recording_id])
	except ThreeCXError as e:
		frappe.throw(f"3CX a refusé la demande de transcription : {e}")


@frappe.whitelist(methods=["POST"])
def refresh_transcription(call_log: str):
	"""Relit transcription, résumé et sentiment de l'enregistrement dans 3CX."""
	doc = _call_log(call_log)
	try:
		data = _client().recording(doc.threecx_recording_id)
	except ThreeCXError as e:
		frappe.throw(str(e))

	if not data.get("IsTranscribed"):
		return {"transcribed": False, "can_be_transcribed": bool(data.get("CanBeTranscribed"))}

	doc.threecx_transcription = data.get("Transcription") or doc.threecx_transcription
	doc.summary = data.get("Summary") or doc.summary
	doc.threecx_sentiment = data.get("SentimentScore") or doc.threecx_sentiment
	doc.save(ignore_permissions=True)
	return {"transcribed": True}


# --- Paramètres -------------------------------------------------------------------


@frappe.whitelist()
def download_template():
	frappe.only_for("System Manager")
	from threecx.threecx.template import build_from_settings

	frappe.local.response.update(
		{"type": "download", "filename": "dokos-erp-3cx.xml", "filecontent": build_from_settings()}
	)


@frappe.whitelist(methods=["POST"])
def test_connection():
	frappe.only_for("System Manager")
	try:
		status = _client().system_status()
	except ThreeCXError as e:
		frappe.throw(f"Connexion à 3CX impossible : {e}")
	return {
		key: status.get(key)
		for key in ("FQDN", "Version", "ProductCode", "LicenseActive", "MaintenanceExpiresAt")
	}


@frappe.whitelist(methods=["POST"])
def sync_now():
	frappe.only_for("System Manager")
	from threecx.tasks import sync_call_history

	try:
		return sync_call_history(manual=True)
	except ThreeCXError as e:
		frappe.throw(str(e))
