"""Student-seller marketplace — admin write actions. Simple read-only
listing of `TOB Seller Account`/`TOB Seller Product` is handled here (with
seller full_name/user_image joined in, which generic REST can't do) rather
than the Flutter admin app hitting `/api/resource/...` directly, matching
`api/sunday_school_admin.py`'s reasoning for its own report-shaped reads.

`provision_seller` is the one action that turns a plain application into
an actually-working seller account — see marketplace/engine.py's module
docstring for the manual, external WP-Admin step (creating the student's
real WCFM vendor user + their own WooCommerce REST API key) that must
happen before an admin calls this.
"""

import frappe

from truth_of_bible.communication.auth import require_admin
from truth_of_bible.marketplace import engine


@frappe.whitelist(methods=["GET"])
def list_seller_applications(status=None):
	require_admin()
	return engine.list_seller_applications(status=status)


@frappe.whitelist(methods=["POST"])
def provision_seller(user, store_name=None, consumer_key=None, consumer_secret=None, admin_note=None):
	require_admin()
	return engine.provision_seller(user, store_name, consumer_key, consumer_secret, admin_note=admin_note)


@frappe.whitelist(methods=["POST"])
def suspend_seller(user, note=None):
	require_admin()
	return engine.suspend_seller(user, note=note)


@frappe.whitelist(methods=["POST"])
def reactivate_seller(user):
	require_admin()
	return engine.reactivate_seller(user)


@frappe.whitelist(methods=["GET"])
def list_pending_products():
	require_admin()
	return engine.list_pending_products()


@frappe.whitelist(methods=["POST"])
def approve_product(ledger_name, note=None):
	require_admin()
	return engine.approve_product(ledger_name, note=note)


@frappe.whitelist(methods=["POST"])
def reject_product(ledger_name, note=None):
	require_admin()
	return engine.reject_product(ledger_name, note=note)
