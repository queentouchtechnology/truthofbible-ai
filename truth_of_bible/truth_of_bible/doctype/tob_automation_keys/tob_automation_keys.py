"""Lets the founder hand automation keys to Claude from the desk (e.g. from a phone) without pasting them into a
chat: the keys stay here, and only a short one-time pickup code is shared. The code works once, for 30 minutes."""

import hmac
import secrets

import frappe
from frappe.model.document import Document
from frappe.rate_limiter import rate_limit
from frappe.utils import add_to_date, get_datetime, now_datetime

DOCTYPE = "TOB Automation Keys"


class TOBAutomationKeys(Document):
	pass


@frappe.whitelist(methods=["POST"])
def new_pickup_code() -> dict:
	frappe.only_for("System Manager")
	code = secrets.token_hex(8)
	expires = add_to_date(now_datetime(), minutes=30)
	frappe.db.set_single_value(DOCTYPE, {"pickup_code": code, "pickup_expires": expires})
	return {"code": code, "expires": str(expires)}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=3600)
def pickup(code: str) -> dict:
	doc = frappe.get_single(DOCTYPE)
	valid = (
		doc.pickup_code
		and doc.pickup_expires
		and get_datetime(doc.pickup_expires) > now_datetime()
		and hmac.compare_digest(str(code or ""), doc.pickup_code)
	)
	if not valid:
		frappe.throw("That pickup code isn't valid or has expired.", frappe.PermissionError)
	keys = {
		"N8N_API_KEY": doc.get_password("n8n_api_key", raise_exception=False),
		"TOB_FRAPPE_API_KEY": doc.frappe_api_key,
		"TOB_FRAPPE_API_SECRET": doc.get_password("frappe_api_secret", raise_exception=False),
	}
	frappe.db.set_single_value(DOCTYPE, {"pickup_code": None, "pickup_expires": None, "last_picked_up": now_datetime()})
	frappe.db.commit()
	return {k: v for k, v in keys.items() if v}
