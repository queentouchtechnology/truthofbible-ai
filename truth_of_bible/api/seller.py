"""Student-seller marketplace — student-facing API. Session-cookie auth,
same closed-doctype discipline as `api/sunday_school.py`: every
`TOB Seller *` doctype grants no REST access to any role but System
Manager, so this module (plus `api/seller_admin.py` for admin actions) is
the only door.

The student never sees a WooCommerce key or talks to edenza.org
directly — every call here goes through `marketplace/engine.py`, which
holds the seller's own key server-side (see that module's docstring for
why that split exists).
"""

import json

import frappe
from frappe import _

from truth_of_bible.marketplace import engine


def _require_login():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in."), frappe.PermissionError)
	return frappe.session.user


@frappe.whitelist(methods=["GET"])
def get_seller_status():
	user = _require_login()
	return engine.get_seller_status(user)


@frappe.whitelist(methods=["POST"])
def apply_to_sell(store_name=None):
	user = _require_login()
	return engine.apply_to_sell(user, store_name)


@frappe.whitelist(methods=["GET"])
def list_my_products(page=1, per_page=20, search=None, status=None):
	user = _require_login()
	return engine.list_products(user, page=int(page), per_page=int(per_page), search=search, status=status)


@frappe.whitelist(methods=["POST"])
def create_product(payload):
	user = _require_login()
	if isinstance(payload, str):
		payload = json.loads(payload)
	return engine.create_product(user, payload)


@frappe.whitelist(methods=["PUT", "POST"])
def update_product(product_id, payload):
	user = _require_login()
	if isinstance(payload, str):
		payload = json.loads(payload)
	return engine.update_product(user, int(product_id), payload)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_product(product_id):
	user = _require_login()
	return engine.delete_product(user, int(product_id))


@frappe.whitelist(methods=["GET"])
def list_my_orders(page=1, per_page=20):
	user = _require_login()
	return engine.list_orders(user, page=int(page), per_page=int(per_page))


@frappe.whitelist(methods=["GET"])
def get_low_stock_products():
	user = _require_login()
	return engine.get_low_stock_products(user)
