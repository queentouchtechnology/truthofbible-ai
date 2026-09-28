import frappe
from frappe.model.document import Document


class TOBSundaySchoolVerseCompletion(Document):
	def validate(self):
		if not self.memory_verse or not self.user:
			frappe.throw("Memory Verse and User are required.")
