"""Méthodes appelées par le serveur 3CX via le template CRM (cf. threecx/threecx/template.py).

Authentification : clé API d'un utilisateur ERP portant le rôle « 3CX Integration ».
Les lectures/écritures se font ensuite en ignorant les permissions, sur ce périmètre précis.
"""

import frappe
from frappe.utils import escape_html

from threecx.install import INTEGRATION_ROLE
from threecx.threecx import contacts
from threecx.threecx.call_logs import CALL_TYPES, Call, parse_duration, upsert_call, utc_to_local


def _check_access():
	frappe.only_for([INTEGRATION_ROLE, "System Manager"])
	if not frappe.db.get_single_value("ThreeCX Settings", "enabled"):
		frappe.throw("L'intégration 3CX est désactivée dans les paramètres 3CX.")
	return frappe.get_cached_doc("ThreeCX Settings")


def _clean(value: str | None) -> str | None:
	"""3CX envoie une chaîne vide (ou parfois la variable non résolue) quand une donnée manque."""
	value = (value or "").strip()
	if not value or (value.startswith("[") and value.endswith("]")):
		return None
	return value


# --- Identification ----------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def lookup(number: str, direction: str | None = None):
	settings = _check_access()
	matches = contacts.find_by_number(number)

	if direction == "Inbound" and settings.notify_incoming_calls:
		_notify_incoming_call(number, matches)

	return {"contacts": matches}


@frappe.whitelist(methods=["POST"])
def lookup_by_email(email: str):
	_check_access()
	return {"contacts": contacts.find_by_email(email)}


@frappe.whitelist(methods=["POST"])
def search_contacts(text: str):
	_check_access()
	return {"contacts": contacts.search(text)}


@frappe.whitelist(methods=["POST"])
def create_contact(first_name=None, last_name=None, number=None, email=None, company=None):
	settings = _check_access()
	if not settings.allow_contact_creation:
		frappe.throw("La création de contacts depuis 3CX est désactivée.")
	entry = contacts.create_contact(
		_clean(first_name), _clean(last_name), _clean(number), _clean(email), _clean(company)
	)
	return {"contacts": [entry]}


def _notify_incoming_call(number: str, matches: list[dict]):
	users = frappe.get_all("User", filters={"threecx_incoming_popup": 1, "enabled": 1}, pluck="name")
	payload = {
		"number": number,
		"matches": [
			{key: m[key] for key in ("id", "type", "display_name", "company", "url")} for m in matches[:3]
		],
	}
	for user in users:
		frappe.publish_realtime("threecx_incoming_call", payload, user=user)


# --- Journalisation ----------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def report_call(**kwargs):
	settings = _check_access()
	data = frappe._dict({key: _clean(value) for key, value in kwargs.items() if key != "cmd"})

	if not settings.log_calls or not data.number:
		return {"logged": False}
	if not data.entity_id and not settings.log_unmatched_calls:
		return {"logged": False}

	call_type = data.call_type if data.call_type in CALL_TYPES else _default_call_type(data.call_direction)
	start = utc_to_local(data.start_time) or frappe.utils.now_datetime()
	established = utc_to_local(data.established_time)
	end = utc_to_local(data.end_time)
	if established and end:
		duration = int((end - established).total_seconds())
	else:
		duration = parse_duration(data.duration)

	agent_name = " ".join(filter(None, [data.agent_first_name, data.agent_last_name])) or None
	doc = upsert_call(
		Call(
			external_number=data.number,
			threecx_call_type=call_type,
			start=start,
			end=end,
			duration=max(duration, 0),
			agent=data.agent,
			agent_name=agent_name,
			agent_email=data.agent_email,
			queue=data.queue_extension,
			contact_name=data.name,
			entity_type=data.entity_type,
			entity_id=data.entity_id,
			transcription=data.transcription,
			summary=data.summary,
			recording_url=data.recording_url,
			source="CRM",
		)
	)
	return {"logged": True, "call_log": doc.name}


@frappe.whitelist(methods=["POST"])
def report_chat(**kwargs):
	settings = _check_access()
	data = frappe._dict({key: _clean(value) for key, value in kwargs.items() if key != "cmd"})
	if not settings.log_chats or not data.chat_messages:
		return {"logged": False}

	reference = None
	if (
		data.entity_type in ("Contact", "Lead")
		and data.entity_id
		and frappe.db.exists(data.entity_type, data.entity_id)
	):
		reference = (data.entity_type, data.entity_id)
	else:
		matches = contacts.find_by_email(data.email) if data.email else contacts.find_by_number(data.number)
		if matches:
			reference = (matches[0]["type"], matches[0]["id"])

	agent = " ".join(filter(None, [data.agent_first_name, data.agent_last_name])) or data.agent
	correspondent = data.name or data.email or data.number or "inconnu"
	communication = frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Chat",
			"sent_or_received": "Received",
			"subject": f"Conversation 3CX avec {correspondent}",
			"content": _chat_html(data.chat_messages, agent, data.duration),
			"sender": data.email,
			"sender_full_name": data.name,
			"phone_no": data.number,
			"reference_doctype": reference[0] if reference else None,
			"reference_name": reference[1] if reference else None,
		}
	)
	if reference and reference[0] == "Contact":
		for doctype, name in contacts.linked_parties(reference[1]):
			communication.add_link(doctype, name)
	communication.insert(ignore_permissions=True)
	return {"logged": True, "communication": communication.name}


def _chat_html(messages: str, agent: str | None, duration: str | None) -> str:
	header = " · ".join(
		filter(None, [f"Agent : {agent}" if agent else None, f"Durée : {duration}" if duration else None])
	)
	body = escape_html(messages).replace("\n", "<br>")
	return f"<p><em>{escape_html(header)}</em></p><p>{body}</p>" if header else f"<p>{body}</p>"


def _default_call_type(direction: str | None) -> str:
	return "Outbound" if direction == "Outbound" else "Inbound"
