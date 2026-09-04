import frappe
from frappe import _
from frappe.model.document import Document


class TOBBibleBattleAnswer(Document):
	def validate(self):
		duplicate = frappe.db.exists(
			"TOB Bible Battle Answer",
			{
				"battle": self.battle,
				"player": self.player,
				"question": self.question,
				"name": ["!=", self.name or ""],
			},
		)
		if duplicate:
			frappe.throw(_("An answer for this question has already been submitted."))
