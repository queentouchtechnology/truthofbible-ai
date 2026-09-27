import frappe
from frappe.model.document import Document


class TOBBibleJourney(Document):
	def validate(self):
		self.title = (self.title or "").strip()
		if not self.title:
			frappe.throw("Title is required.")
