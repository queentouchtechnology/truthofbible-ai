import frappe
from frappe.model.document import Document


class TOBSundaySchoolProfile(Document):
	def validate(self):
		if not self.user:
			frappe.throw("User is required.")
