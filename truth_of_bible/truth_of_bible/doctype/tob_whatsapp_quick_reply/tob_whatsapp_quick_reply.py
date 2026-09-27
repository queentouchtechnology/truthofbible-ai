import frappe
from frappe.model.document import Document


class TOBWhatsAppQuickReply(Document):
	def validate(self):
		self.title = (self.title or "").strip()
		self.body = (self.body or "").strip()
		if not self.title or not self.body:
			frappe.throw("Both Title and Reply Text are required.")
