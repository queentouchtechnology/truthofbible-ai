import frappe
from frappe import _
from frappe.model.document import Document


class TOBBibleTopicTranslation(Document):
	def validate(self):
		existing = frappe.db.get_value(
			"TOB Bible Topic Translation",
			{"topic": self.topic, "language": self.language, "name": ["!=", self.name]},
			"name",
		)
		if existing:
			frappe.throw(
				_("{0} already has a translation for {1} ({2}).").format(self.topic, self.language, existing)
			)
