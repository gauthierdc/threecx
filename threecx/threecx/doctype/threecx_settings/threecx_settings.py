# Copyright (c) 2026, Verre & Transparence and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import get_url


class ThreeCXSettings(Document):
	def validate(self):
		for field in ("pbx_url", "erp_url"):
			if self.get(field):
				self.set(field, self.get(field).strip().rstrip("/"))
		if self.match_digits and not 6 <= self.match_digits <= 15:
			frappe.throw("Le nombre de chiffres comparés doit être compris entre 6 et 15.")

	def on_update(self):
		# Le jeton OAuth dépend du client ID / secret et de l'URL du PBX.
		from threecx.threecx.client import clear_token_cache

		clear_token_cache()

	def get_erp_url(self) -> str:
		return self.erp_url or get_url()
