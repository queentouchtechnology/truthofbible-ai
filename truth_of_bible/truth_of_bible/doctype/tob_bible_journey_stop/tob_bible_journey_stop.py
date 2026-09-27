import frappe
from frappe.model.document import Document


class TOBBibleJourneyStop(Document):
	def validate(self):
		if not self.stop_number or self.stop_number < 1:
			frappe.throw("Stop must be 1 or greater.")
		if not self.place:
			frappe.throw("Place is required.")
