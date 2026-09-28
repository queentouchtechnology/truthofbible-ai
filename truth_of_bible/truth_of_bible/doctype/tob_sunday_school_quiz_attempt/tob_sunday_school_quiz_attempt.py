import frappe
from frappe.model.document import Document


class TOBSundaySchoolQuizAttempt(Document):
	def validate(self):
		if not self.quiz or not self.user:
			frappe.throw("Quiz and User are required.")
