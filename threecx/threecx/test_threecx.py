import frappe
from frappe.tests.utils import FrappeTestCase

from threecx.api import crm
from threecx.tasks import call_from_xapi
from threecx.threecx.call_logs import upsert_call


class TestThreeCX(FrappeTestCase):
	def setUp(self):
		settings = frappe.get_single("ThreeCX Settings")
		settings.update(
			{
				"enabled": 1,
				"erp_url": "https://erp.test",
				"match_digits": 9,
				"lookup_contacts": 1,
				"lookup_leads": 1,
				"contact_url_target": "Contact",
				"log_calls": 1,
				"log_unmatched_calls": 0,
			}
		)
		settings.save()
		frappe.clear_document_cache("ThreeCX Settings", "ThreeCX Settings")

		self.contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Jeanne",
				"last_name": "Test3CX",
				"company_name": "Verrerie Test",
			}
		)
		self.contact.add_phone("06 12 34 56 78", is_primary_phone=1)
		self.contact.insert(ignore_permissions=True)

	def test_lookup_matches_international_format(self):
		result = crm.lookup("+33612345678", "Inbound")
		match = next(c for c in result["contacts"] if c["id"] == self.contact.name)
		self.assertEqual(match["phone"], "+33612345678")
		self.assertEqual(match["company"], "Verrerie Test")
		self.assertTrue(match["url"].startswith("https://erp.test/app/contact/"))

	def test_short_number_never_matches(self):
		self.assertEqual(crm.lookup("101")["contacts"], [])

	def test_report_call_then_xapi_sync_completes_same_log(self):
		crm.report_call(
			call_type="Inbound",
			number="+33612345678",
			entity_id=self.contact.name,
			entity_type="Contact",
			agent="101",
			duration="00:02:05",
			start_time="2026-11-14T09:00:00Z",
			summary="Demande de devis",
		)
		call = call_from_xapi(
			{
				"Direction": "Inbound",
				"Answered": True,
				"SourceCallerId": "0612345678",
				"DestinationDn": "101",
				"StartTime": "2026-11-14T09:00:20Z",
				"TalkingDuration": "PT2M5S",
				"Transcription": "Bonjour, je voudrais un devis.",
				"MainCallHistoryId": "test-3cx-1",
			}
		)
		log = upsert_call(call)

		logs = frappe.get_all("Call Log", filters={"from": ["like", "%612345678"], "name": ["like", "3cx-%"]})
		self.assertEqual(len(logs), 1)
		self.assertEqual(log.summary, "Demande de devis")
		self.assertEqual(log.threecx_transcription, "Bonjour, je voudrais un devis.")
		self.assertEqual(log.duration, 125)
		self.assertIn(
			("Contact", self.contact.name), [(link.link_doctype, link.link_name) for link in log.links]
		)

	def test_unmatched_call_not_logged_by_default(self):
		result = crm.report_call(call_type="Missed", number="+33100000000", start_time="2026-11-14T09:00:00Z")
		self.assertFalse(result["logged"])

	def test_internal_xapi_rows_are_skipped(self):
		self.assertIsNone(call_from_xapi({"Direction": "Internal", "StartTime": "2026-11-14T09:00:00Z"}))
		self.assertIsNone(call_from_xapi({"Direction": "Inbound", "Indent": 1}))

	def test_lead_and_its_contact_are_one_match(self):
		lead = frappe.get_doc(
			{"doctype": "Lead", "first_name": "Paul", "last_name": "Test3CX", "phone": "+33 1 98 76 12 34"}
		).insert(ignore_permissions=True)
		contact = frappe.get_doc({"doctype": "Contact", "first_name": "Paul", "last_name": "Test3CX"})
		contact.add_phone("01 98 76 12 34")
		contact.append("links", {"link_doctype": "Lead", "link_name": lead.name})
		contact.insert(ignore_permissions=True)

		matches = crm.lookup("0198761234")["contacts"]
		self.assertEqual([(m["type"], m["id"]) for m in matches], [("Lead", lead.name)])
