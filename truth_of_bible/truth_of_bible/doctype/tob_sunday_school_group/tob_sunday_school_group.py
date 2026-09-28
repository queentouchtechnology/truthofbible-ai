import frappe
from frappe.model.document import Document


class TOBSundaySchoolGroup(Document):
	def validate(self):
		self.group_name = (self.group_name or "").strip()
		if not self.group_name:
			frappe.throw("Group Name is required.")
