import frappe
from frappe.model.document import Document


class TOBSundaySchoolWeeklyQuiz(Document):
	def validate(self):
		self.title = (self.title or "").strip()
		if not self.title:
			frappe.throw("Title is required.")
		if not self.week_start:
			frappe.throw("Week Start is required.")
