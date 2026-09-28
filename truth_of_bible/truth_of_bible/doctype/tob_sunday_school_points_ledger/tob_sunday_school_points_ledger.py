import frappe
from frappe.model.document import Document


class TOBSundaySchoolPointsLedger(Document):
	def validate(self):
		if not self.user or not self.week_start:
			frappe.throw("User and Week Start are required.")
		if self.points is None:
			frappe.throw("Points is required.")
