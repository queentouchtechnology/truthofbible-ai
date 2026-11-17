import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime


class TOBFestivalTheme(Document):
	def validate(self):
		if self.start and self.end and get_datetime(self.end) <= get_datetime(self.start):
			frappe.throw(_("End must be after Start."))
		if self.bible_book and not (1 <= int(self.bible_book) <= 66):
			frappe.throw(_("Book Number is 1 (Genesis) to 66 (Revelation)."))
		if self.verse_start and not self.verse_end:
			self.verse_end = self.verse_start

