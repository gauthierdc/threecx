import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

INTEGRATION_ROLE = "3CX Integration"


def after_install():
	after_migrate()


def after_migrate():
	create_integration_role()
	create_custom_fields(get_custom_fields(), update=True)


def create_integration_role():
	"""Rôle porté par l'utilisateur technique dont la clé API est saisie dans 3CX."""
	if frappe.db.exists("Role", INTEGRATION_ROLE):
		return
	frappe.get_doc({"doctype": "Role", "role_name": INTEGRATION_ROLE, "desk_access": 0}).insert(
		ignore_permissions=True
	)


def get_custom_fields():
	return {
		"Call Log": [
			{
				"fieldname": "threecx_section",
				"fieldtype": "Section Break",
				"label": "3CX",
				"insert_after": "call_received_by",
			},
			{
				"fieldname": "threecx_call_type",
				"fieldtype": "Select",
				"label": "Type d'appel 3CX",
				"options": "\nInbound\nOutbound\nMissed\nNotanswered",
				"read_only": 1,
				"in_standard_filter": 1,
				"insert_after": "threecx_section",
			},
			{
				"fieldname": "threecx_agent",
				"fieldtype": "Data",
				"label": "Poste 3CX",
				"read_only": 1,
				"in_standard_filter": 1,
				"insert_after": "threecx_call_type",
			},
			{
				"fieldname": "threecx_agent_name",
				"fieldtype": "Data",
				"label": "Agent",
				"read_only": 1,
				"in_list_view": 1,
				"insert_after": "threecx_agent",
			},
			{
				"fieldname": "threecx_queue",
				"fieldtype": "Data",
				"label": "File d'attente / groupe",
				"read_only": 1,
				"insert_after": "threecx_agent_name",
			},
			{
				"fieldname": "threecx_column_break",
				"fieldtype": "Column Break",
				"insert_after": "threecx_queue",
			},
			{
				"fieldname": "threecx_contact_name",
				"fieldtype": "Data",
				"label": "Correspondant",
				"read_only": 1,
				"in_list_view": 1,
				"insert_after": "threecx_column_break",
			},
			{
				"fieldname": "threecx_source",
				"fieldtype": "Select",
				"label": "Source",
				"options": "\nCRM\nXAPI",
				"read_only": 1,
				"insert_after": "threecx_contact_name",
			},
			{
				"fieldname": "threecx_cdr_id",
				"fieldtype": "Data",
				"label": "ID historique 3CX",
				"read_only": 1,
				"search_index": 1,
				"insert_after": "threecx_source",
			},
			{
				"fieldname": "threecx_recording_id",
				"fieldtype": "Int",
				"label": "ID enregistrement 3CX",
				"read_only": 1,
				"insert_after": "threecx_cdr_id",
			},
			{
				"fieldname": "threecx_recording_url",
				"fieldtype": "Small Text",
				"label": "URL d'enregistrement 3CX",
				"read_only": 1,
				"insert_after": "threecx_recording_id",
			},
			{
				"fieldname": "threecx_sentiment",
				"fieldtype": "Float",
				"label": "Score de sentiment",
				"read_only": 1,
				"insert_after": "threecx_recording_url",
			},
			{
				"fieldname": "threecx_transcription_section",
				"fieldtype": "Section Break",
				"label": "Transcription",
				"collapsible": 1,
				"collapsible_depends_on": "threecx_transcription",
				"insert_after": "threecx_sentiment",
			},
			{
				"fieldname": "threecx_transcription",
				"fieldtype": "Long Text",
				"label": "Transcription",
				"read_only": 1,
				"insert_after": "threecx_transcription_section",
			},
		],
		"User": [
			{
				"fieldname": "threecx_extension",
				"fieldtype": "Data",
				"label": "Poste 3CX",
				"description": "Numéro de poste 3CX de l'utilisateur (click-to-call et attribution des appels).",
				"insert_after": "mobile_no",
			},
			{
				"fieldname": "threecx_incoming_popup",
				"fieldtype": "Check",
				"label": "Notification des appels entrants 3CX",
				"insert_after": "threecx_extension",
			},
		],
	}
