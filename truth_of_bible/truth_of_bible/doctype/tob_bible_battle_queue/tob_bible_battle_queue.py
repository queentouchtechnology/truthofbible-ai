import frappe
from frappe import _
from frappe.model.document import Document


class TOBBibleBattleQueue(Document):
	def validate(self):
		if self.status != "Searching":
			return
		duplicate = frappe.db.exists(
			"TOB Bible Battle Queue",
			{"player": self.player, "status": "Searching", "name": ["!=", self.name or ""]},
		)
		if duplicate:
			frappe.throw(_("You are already searching for an opponent."))
