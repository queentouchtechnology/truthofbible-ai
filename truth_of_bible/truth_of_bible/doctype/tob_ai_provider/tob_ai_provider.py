import frappe
from frappe import _
from frappe.model.document import Document


class TOBAIProvider(Document):
	def validate(self):
		if not self.is_fallback:
			return
		existing = frappe.db.get_value(
			"TOB AI Provider", {"is_fallback": 1, "name": ["!=", self.name]}, "name"
		)
		if existing:
			frappe.throw(
				_("{0} is already the fallback provider. Unset it before making {1} the fallback.").format(
					existing, self.name
				)
			)
