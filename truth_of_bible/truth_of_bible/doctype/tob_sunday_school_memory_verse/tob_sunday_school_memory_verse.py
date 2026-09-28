import frappe
from frappe.model.document import Document


class TOBSundaySchoolMemoryVerse(Document):
	def validate(self):
		self.title = (self.title or "").strip()
		self.reference = (self.reference or "").strip()
		if not self.title or not self.reference:
			frappe.throw("Title and Verse Reference are required.")
		if not self.week_start:
			frappe.throw("Week Start is required.")
