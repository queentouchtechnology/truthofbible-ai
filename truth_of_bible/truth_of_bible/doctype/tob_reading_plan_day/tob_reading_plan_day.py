import frappe
from frappe.model.document import Document


class TOBReadingPlanDay(Document):
	def validate(self):
		self.reference_label = (self.reference_label or "").strip()
		if not self.reference_label:
			frappe.throw("Reference Label is required.")
		if not self.day_number or self.day_number < 1:
			frappe.throw("Day must be 1 or greater.")
		if not self.book_id or not (1 <= self.book_id <= 66):
			frappe.throw("Book ID must be between 1 and 66.")
