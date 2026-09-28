import frappe
from frappe.model.document import Document


class TOBSellerOrderLine(Document):
	def validate(self):
		if not self.seller or not self.order_id or not self.product_id:
			frappe.throw("Seller, Order ID, and Product ID are required.")
