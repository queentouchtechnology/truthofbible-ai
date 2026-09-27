import frappe
from frappe.model.document import Document


class TOBBiblePlace(Document):
	def validate(self):
		self.title = (self.title or "").strip()
		if not self.title:
			frappe.throw("Title is required.")
		if self.latitude is None or self.longitude is None:
			frappe.throw("Latitude and Longitude are required.")
		if not (-90 <= self.latitude <= 90):
			frappe.throw("Latitude must be between -90 and 90.")
		if not (-180 <= self.longitude <= 180):
			frappe.throw("Longitude must be between -180 and 180.")
