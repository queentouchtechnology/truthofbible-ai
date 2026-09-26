import frappe
from frappe.model.document import Document


class TOBEncouragementMessage(Document):
	def validate(self):
		self.title = (self.title or "").strip()
		self.body = (self.body or "").strip()
		if not self.title or not self.body:
			frappe.throw("Both Title and Body are required.")
		if self.weight is not None and self.weight < 1:
			self.weight = 1
