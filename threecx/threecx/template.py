"""Génération du template XML « CRM côté serveur » à importer dans la console 3CX.

Référence : https://www.3cx.com/docs/crm-template-xml-description/
Toutes les requêtes sont des POST JSON vers les méthodes de `threecx.api.crm`, authentifiées par
la clé API d'un utilisateur ERP (paramètres ApiKey / ApiSecret saisis dans la console 3CX).
"""

import xml.etree.ElementTree as ET

import frappe

API = "[ErpUrl]/api/method/threecx.api.crm"
TEMPLATE_VERSION = "1"

# Sorties d'une correspondance de contact -> chemin dans la réponse Frappe.
CONTACT_VARIABLES = {
	"EntityId": "id",
	"EntityType": "type",
	"ContactUrl": "url",
	"FirstName": "first_name",
	"LastName": "last_name",
	"CompanyName": "company",
	"Email": "email",
	"PhoneMobile": "mobile",
	"PhoneBusiness": "phone",
}

REPORT_CALL_VALUES = {
	"call_type": "[CallType]",
	"number": "[Number]",
	"call_direction": "[CallDirection]",
	"name": "[Name]",
	"entity_id": "[EntityId]",
	"entity_type": "[EntityType]",
	"queue_extension": "[QueueExtension]",
	"agent": "[Agent]",
	"agent_first_name": "[AgentFirstName]",
	"agent_last_name": "[AgentLastName]",
	"agent_email": "[AgentEmail]",
	"duration": "[Duration]",
	"start_time": '[[CallStartTimeUTC].ToString("yyyy-MM-ddTHH:mm:ssZ")]',
	"established_time": '[[CallEstablishedTimeUTC].ToString("yyyy-MM-ddTHH:mm:ssZ")]',
	"end_time": '[[CallEndTimeUTC].ToString("yyyy-MM-ddTHH:mm:ssZ")]',
}

# Variables de journalisation apparues avec l'IA de 3CX V20.
REPORT_CALL_VALUES_V20 = {
	"transcription": "[Transcription]",
	"summary": "[Summary]",
	"recording_url": "[RecordingUrl]",
}

REPORT_CHAT_VALUES = {
	"number": "[Number]",
	"email": "[Email]",
	"name": "[Name]",
	"entity_id": "[EntityId]",
	"entity_type": "[EntityType]",
	"queue_extension": "[QueueExtension]",
	"agent": "[Agent]",
	"agent_first_name": "[AgentFirstName]",
	"agent_last_name": "[AgentLastName]",
	"agent_email": "[AgentEmail]",
	"duration": "[Duration]",
	"chat_messages": "[ChatMessages]",
}


def build_template(erp_url: str, version: str = "V20") -> str:
	crm = ET.Element(
		"Crm",
		{
			"xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
			"xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
			"Country": "FR",
			"Name": "Dokos ERP",
			"Version": TEMPLATE_VERSION,
			"SupportsEmojis": "true",
		},
	)
	# Le rapprochement se fait côté ERP sur les derniers chiffres : on transmet le numéro brut.
	ET.SubElement(crm, "Number", {"Prefix": "AsIs", "MaxLength": ""})
	ET.SubElement(crm, "Connection", {"MaxConcurrentRequests": "4"})

	parameters = ET.SubElement(crm, "Parameters")
	for name, type_, title, default in (
		("ErpUrl", "String", "URL de l'ERP", erp_url),
		("ApiKey", "String", "Clé API (API Key de l'utilisateur ERP)", ""),
		("ApiSecret", "Password", "Secret API (API Secret de l'utilisateur ERP)", ""),
	):
		ET.SubElement(
			parameters,
			"Parameter",
			{
				"Name": name,
				"Type": type_,
				"Parent": "Connexion à l'ERP",
				"Editor": "String",
				"Title": title,
				"Default": default,
			},
		)

	ET.SubElement(crm, "Authentication", {"Type": "No"})

	scenarios = ET.SubElement(crm, "Scenarios")
	_contact_scenario(scenarios, "", "lookup", {"number": "[Number]", "direction": "[CallDirection]"})
	_contact_scenario(scenarios, "LookupByEmail", "lookup_by_email", {"email": "[Email]"})
	_contact_scenario(scenarios, "SearchContacts", "search_contacts", {"text": "[SearchText]"})
	_contact_scenario(
		scenarios,
		"CreateContactRecordFromClient",
		"create_contact",
		{
			"first_name": "[FirstName]",
			"last_name": "[LastName]",
			"number": "[Number]",
			"email": "[Email]",
			"company": "[Company]",
		},
	)

	report_call_values = dict(REPORT_CALL_VALUES)
	if version == "V20":
		report_call_values.update(REPORT_CALL_VALUES_V20)
	_report_scenario(scenarios, "ReportCall", "report_call", report_call_values)
	_report_scenario(scenarios, "ReportChat", "report_chat", REPORT_CHAT_VALUES)

	ET.indent(crm, space="  ")
	return '<?xml version="1.0"?>\n' + ET.tostring(crm, encoding="unicode") + "\n"


def _request(scenario: ET.Element, method: str, values: dict) -> ET.Element:
	request = ET.SubElement(
		scenario,
		"Request",
		{
			"SkipIf": "",
			"Url": f"{API}.{method}",
			"MessagePasses": "0",
			"RequestContentType": "application/json",
			"RequestEncoding": "Json",
			"RequestType": "Post",
			"ResponseType": "Json",
		},
	)
	headers = ET.SubElement(request, "Headers")
	_value(headers, "Authorization", "token [ApiKey]:[ApiSecret]")
	post_values = ET.SubElement(request, "PostValues")
	for key, expression in values.items():
		_value(post_values, key, expression)
	return request


def _value(parent: ET.Element, key: str, expression: str):
	ET.SubElement(parent, "Value", {"Key": key, "Passes": "1", "Type": "String"}).text = expression


def _contact_scenario(scenarios: ET.Element, scenario_id: str, method: str, values: dict):
	scenario = ET.SubElement(scenarios, "Scenario", {"Id": scenario_id, "Type": "REST"})
	_request(scenario, method, values)

	# Réponse Frappe : {"message": {"contacts": [{...}, ...]}} — un enregistrement par contact.
	rules = ET.SubElement(scenario, "Rules")
	ET.SubElement(rules, "Rule", {"Type": "Any"}).text = "message.contacts.id"

	variables = ET.SubElement(scenario, "Variables")
	for name, path in CONTACT_VARIABLES.items():
		variable = ET.SubElement(variables, "Variable", {"Name": name, "Path": f"message.contacts.{path}"})
		ET.SubElement(variable, "Filter")

	outputs = ET.SubElement(scenario, "Outputs", {"AllowEmpty": "false"})
	for name in CONTACT_VARIABLES:
		ET.SubElement(outputs, "Output", {"Type": name, "Passes": "0", "Value": f"[{name}]"})


def _report_scenario(scenarios: ET.Element, scenario_id: str, method: str, values: dict):
	# La journalisation ne renvoie rien : ni Rules, ni Variables, ni Outputs (cf. doc 3CX).
	scenario = ET.SubElement(scenarios, "Scenario", {"Id": scenario_id, "Type": "REST"})
	_request(scenario, method, values)


def build_from_settings() -> str:
	settings = frappe.get_cached_doc("ThreeCX Settings")
	return build_template(settings.get_erp_url(), settings.pbx_version or "V20")
