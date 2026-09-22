import frappe
from frappe.model.document import Document


class TOBNotificationTemplate(Document):
	def validate(self):
		self.event_code = (self.event_code or "").strip().upper().replace(" ", "_")
		if not self.event_code:
			frappe.throw("Event Code is required.")
