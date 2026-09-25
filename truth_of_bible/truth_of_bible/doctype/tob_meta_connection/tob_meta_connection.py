from frappe.model.document import Document


class TOBMetaConnection(Document):
	def validate(self):
		self.page_id = (self.page_id or "").strip()
		self.app_id = (self.app_id or "").strip()
		if (self.warn_days or 0) < 1:
			self.warn_days = 14
