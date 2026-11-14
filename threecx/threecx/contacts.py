"""Recherche des contacts ERP à partir de ce que 3CX connaît : numéro, email ou texte libre.

Chaque correspondance est renvoyée sous la forme d'un dict « entrée 3CX » (cf. `_contact_entry`),
directement consommé par le template CRM et par le journal d'appels.
"""

import re
from urllib.parse import quote

import frappe

MIN_DIGITS = 6
MAX_RESULTS = 10


def digits(number: str | None) -> str:
	return re.sub(r"\D", "", number or "")


def number_suffix(number: str | None, match_digits: int) -> str | None:
	"""Derniers chiffres significatifs d'un numéro, ou None s'il est trop court (poste interne…)."""
	d = digits(number)
	if len(d) < MIN_DIGITS:
		return None
	return d[-match_digits:]


def _settings():
	return frappe.get_cached_doc("ThreeCX Settings")


def _digits_only_sql(column: str) -> str:
	if frappe.db.db_type == "postgres":
		return f"regexp_replace({column}, '[^0-9]', '', 'g')"
	return f"regexp_replace({column}, '[^0-9]', '')"


# --- Recherche ---------------------------------------------------------------


def find_by_number(number: str) -> list[dict]:
	settings = _settings()
	suffix = number_suffix(number, settings.match_digits or 9)
	if not suffix:
		return []

	pattern = f"%{suffix}"
	entries = []
	if settings.lookup_contacts:
		contacts = frappe.db.sql_list(
			f"""
			select distinct parent from `tabContact Phone`
			where parenttype = 'Contact' and {_digits_only_sql("phone")} like %(pattern)s
			limit {MAX_RESULTS}
			""",
			{"pattern": pattern},
		)
		entries += [_contact_entry(name, number) for name in contacts]

	if settings.lookup_leads:
		phone_match = " or ".join(
			f"{_digits_only_sql(col)} like %(pattern)s" for col in ("phone", "mobile_no", "whatsapp_no")
		)
		leads = frappe.db.sql_list(
			f"""
			select name from `tabLead`
			where status != 'Converted' and ({phone_match})
			order by modified desc
			limit {MAX_RESULTS}
			""",
			{"pattern": pattern},
		)
		entries += [_lead_entry(name, number) for name in leads]

	return _deduplicate(entries)


def find_by_email(email: str) -> list[dict]:
	email = (email or "").strip()
	if not email:
		return []

	settings = _settings()
	entries = []
	if settings.lookup_contacts:
		contacts = frappe.get_all(
			"Contact Email",
			filters={"email_id": email, "parenttype": "Contact"},
			pluck="parent",
			limit=MAX_RESULTS,
		)
		entries += [_contact_entry(name, email=email) for name in dict.fromkeys(contacts)]
	if settings.lookup_leads:
		leads = frappe.get_all(
			"Lead",
			filters={"email_id": email, "status": ["!=", "Converted"]},
			pluck="name",
			limit=MAX_RESULTS,
		)
		entries += [_lead_entry(name, email=email) for name in leads]
	return _deduplicate(entries)


def search(text: str) -> list[dict]:
	"""Recherche plein texte depuis le client 3CX (nom, société, email ou numéro)."""
	text = (text or "").strip()
	if len(text) < 2:
		return []

	settings = _settings()
	entries = []
	like = f"%{text}%"

	if settings.lookup_contacts:
		contacts = frappe.get_all(
			"Contact",
			or_filters={
				"full_name": ["like", like],
				"company_name": ["like", like],
				"email_id": ["like", like],
			},
			pluck="name",
			limit=MAX_RESULTS,
		)
		if len(digits(text)) >= MIN_DIGITS and len(contacts) < MAX_RESULTS:
			contacts += [e["id"] for e in find_by_number(text) if e["type"] == "Contact"]
		entries += [_contact_entry(name) for name in dict.fromkeys(contacts)]

	if settings.lookup_leads:
		leads = frappe.get_all(
			"Lead",
			filters={"status": ["!=", "Converted"]},
			or_filters={
				"lead_name": ["like", like],
				"company_name": ["like", like],
				"email_id": ["like", like],
			},
			pluck="name",
			limit=MAX_RESULTS,
		)
		entries += [_lead_entry(name) for name in leads]

	return _deduplicate(entries)[:MAX_RESULTS]


def _deduplicate(entries: list[dict | None]) -> list[dict]:
	"""Un prospect a souvent un Contact lié (créé avec lui) : 3CX afficherait deux correspondances.

	On garde le prospect, sauf si le contact est aussi rattaché à un client ou un fournisseur.
	"""
	entries = [e for e in entries if e]
	lead_ids = {e["id"] for e in entries if e["type"] == "Lead"}
	contact_ids = [e["id"] for e in entries if e["type"] == "Contact"]
	if not lead_ids or not contact_ids:
		return entries

	contact_leads = frappe.get_all(
		"Dynamic Link",
		filters={
			"parenttype": "Contact",
			"parent": ["in", contact_ids],
			"link_doctype": "Lead",
			"link_name": ["in", list(lead_ids)],
		},
		fields=["parent", "link_name"],
	)
	drop = set()
	for link in contact_leads:
		contact = next(e for e in entries if e["type"] == "Contact" and e["id"] == link.parent)
		drop.add(("Lead", link.link_name) if contact["parties"] else ("Contact", link.parent))
	return [e for e in entries if (e["type"], e["id"]) not in drop]


# --- Création ----------------------------------------------------------------


def create_contact(first_name=None, last_name=None, number=None, email=None, company=None) -> dict:
	contact = frappe.new_doc("Contact")
	contact.first_name = first_name or (None if last_name or company else number or email)
	contact.last_name = last_name
	contact.company_name = company
	if number:
		contact.add_phone(number, is_primary_phone=1)
	if email:
		contact.add_email(email, is_primary=1)

	if company:
		for doctype, title_field in (("Customer", "customer_name"), ("Supplier", "supplier_name")):
			if party := frappe.db.get_value(doctype, {title_field: company}):
				contact.append("links", {"link_doctype": doctype, "link_name": party})
				break

	contact.insert(ignore_permissions=True)
	return _contact_entry(contact.name, number, email)


# --- Entrées renvoyées à 3CX -----------------------------------------------------


def linked_parties(contact: str) -> list[tuple[str, str]]:
	links = frappe.get_all(
		"Dynamic Link",
		filters={
			"parenttype": "Contact",
			"parent": contact,
			"link_doctype": ["in", ["Customer", "Supplier"]],
		},
		fields=["link_doctype", "link_name"],
		order_by="idx asc",
	)
	return [(link.link_doctype, link.link_name) for link in links]


def doc_url(doctype: str, name: str) -> str:
	return f"{_settings().get_erp_url()}/app/{frappe.scrub(doctype).replace('_', '-')}/{quote(name, safe='')}"


def _contact_entry(name: str, number: str | None = None, email: str | None = None) -> dict | None:
	contact = frappe.db.get_value(
		"Contact",
		name,
		["first_name", "last_name", "company_name", "email_id", "mobile_no", "phone"],
		as_dict=True,
	)
	if not contact:
		return None

	parties = linked_parties(name)
	company = contact.company_name
	if not company and parties:
		doctype, party = parties[0]
		company = frappe.db.get_value(doctype, party, frappe.get_meta(doctype).get_title_field())

	url = doc_url("Contact", name)
	if parties and _settings().contact_url_target != "Contact":
		url = doc_url(*parties[0])

	return _entry(
		"Contact",
		name,
		url=url,
		first_name=contact.first_name,
		last_name=contact.last_name,
		company=company,
		email=email or contact.email_id,
		mobile=contact.mobile_no,
		phone=number or contact.phone or contact.mobile_no,
		parties=parties,
	)


def _lead_entry(name: str, number: str | None = None, email: str | None = None) -> dict | None:
	lead = frappe.db.get_value(
		"Lead",
		name,
		["first_name", "last_name", "lead_name", "company_name", "email_id", "mobile_no", "phone"],
		as_dict=True,
	)
	if not lead:
		return None

	return _entry(
		"Lead",
		name,
		url=doc_url("Lead", name),
		first_name=lead.first_name or (None if lead.last_name else lead.lead_name),
		last_name=lead.last_name,
		company=lead.company_name,
		email=email or lead.email_id,
		mobile=lead.mobile_no,
		phone=number or lead.phone or lead.mobile_no,
	)


def _entry(doctype, name, *, url, first_name, last_name, company, email, mobile, phone, parties=()) -> dict:
	# 3CX exige au moins un prénom, un nom ou une société pour accepter la correspondance.
	if not (first_name or last_name or company):
		first_name = name
	display_name = " ".join(filter(None, [first_name, last_name])) or company
	return {
		"id": name,
		"type": doctype,
		"url": url,
		"first_name": first_name or "",
		"last_name": last_name or "",
		"display_name": display_name,
		"company": company or "",
		"email": email or "",
		"mobile": mobile or "",
		# 3CX vérifie que l'un des numéros renvoyés est celui recherché : on renvoie le numéro tel
		# qu'il nous a été transmis, le rapprochement ayant déjà été fait sur les derniers chiffres.
		"phone": phone or "",
		"parties": [list(p) for p in parties],
	}
