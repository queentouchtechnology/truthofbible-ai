import frappe
from frappe import _
from frappe.model.document import Document


class TOBContentTranslation(Document):
	def validate(self):
		existing = frappe.db.get_value(
			"TOB Content Translation",
			{
				"source_doctype": self.source_doctype,
				"source_name": self.source_name,
				"field": self.field,
				"language": self.language,
				"name": ["!=", self.name],
			},
			"name",
		)
		if existing:
			frappe.throw(
				_("{0}.{1} ({2}) already has a {3} translation ({4}).").format(
					self.source_doctype, self.source_name, self.field, self.language, existing
				)
			)
