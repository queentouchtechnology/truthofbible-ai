import frappe
from frappe.model.document import Document


class TOBSundaySchoolAttendance(Document):
	def validate(self):
		if not self.user or not self.week_start:
			frappe.throw("User and Week Start are required.")
