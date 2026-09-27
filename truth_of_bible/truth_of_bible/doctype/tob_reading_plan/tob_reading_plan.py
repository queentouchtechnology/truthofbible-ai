import frappe
from frappe.model.document import Document


class TOBReadingPlan(Document):
	def validate(self):
		self.title = (self.title or "").strip()
		if not self.title:
			frappe.throw("Title is required.")
		if self.duration_days is not None and self.duration_days < 1:
			self.duration_days = 1
