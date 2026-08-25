import frappe
from frappe import _
from frappe.model.document import Document


class TOBAIModel(Document):
	def validate(self):
		if not self.default_for_task:
			return
		existing = frappe.db.get_value(
			"TOB AI Model", {"default_for_task": self.default_for_task, "name": ["!=", self.name]}, "name"
		)
		if existing:
			frappe.throw(
				_("{0} is already the default model for task '{1}'.").format(existing, self.default_for_task)
			)
