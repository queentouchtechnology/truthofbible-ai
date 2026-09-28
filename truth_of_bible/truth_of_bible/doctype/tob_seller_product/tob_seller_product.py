import frappe
from frappe.model.document import Document


class TOBSellerProduct(Document):
	def validate(self):
		if not self.seller or not self.product_id:
			frappe.throw("Seller and Product ID are required.")
