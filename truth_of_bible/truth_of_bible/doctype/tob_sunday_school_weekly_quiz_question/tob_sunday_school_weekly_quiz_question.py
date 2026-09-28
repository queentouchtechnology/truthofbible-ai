import frappe
from frappe.model.document import Document


class TOBSundaySchoolWeeklyQuizQuestion(Document):
	def validate(self):
		if not self.question_number or self.question_number < 1:
			frappe.throw("Question # must be 1 or greater.")
		if not (self.question or "").strip():
			frappe.throw("Question is required.")
