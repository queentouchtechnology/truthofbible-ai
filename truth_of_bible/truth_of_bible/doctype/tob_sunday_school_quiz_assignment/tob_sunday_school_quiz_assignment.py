import frappe
from frappe.model.document import Document


class TOBSundaySchoolQuizAssignment(Document):
	def validate(self):
		if not self.lms_quiz or not self.quiz_type or not self.week_start:
			frappe.throw("LMS Quiz, Quiz Type, and Week Start are required.")
