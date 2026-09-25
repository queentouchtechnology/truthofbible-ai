"""Whitelisted endpoints for the Rewards screen. Session-cookie auth — the
logged-in user's own session, never a client-supplied user id, exactly like
`analytics.record_batch`: points must only ever move for the person who
earned them.

`country` (ISO code, from the device region) is optional everywhere: it only
decides whether Edenza shop coupons are offered (India only) — every other
member uses the wallet."""

import frappe
from frappe.rate_limiter import rate_limit

from truth_of_bible.rewards import engine, history, topup


def _user() -> str:
	user = frappe.session.user
	if user in ("Guest", "Administrator"):
		frappe.throw(frappe._("Please log in to use rewards."), frappe.PermissionError)
	return user


@frappe.whitelist(methods=["GET"])
def get_rewards(country=None):
	return engine.overview(_user(), country)


@frappe.whitelist(methods=["POST"])
def check_in(country=None):
	user = _user()
	result = engine.check_in(user)
	return {**result, "overview": engine.overview(user, country)}


@frappe.whitelist(methods=["POST"])
def record_share(country=None):
	user = _user()
	result = engine.record_share(user)
	return {**result, "overview": engine.overview(user, country)}


@frappe.whitelist(methods=["POST"])
def claim_profile(country=None):
	user = _user()
	result = engine.claim_profile(user)
	return {**result, "overview": engine.overview(user, country)}


@frappe.whitelist(methods=["POST"])
def claim_referral(code, country=None):
	user = _user()
	result = engine.claim_referral(user, code)
	return {**result, "overview": engine.overview(user, country)}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=60)
def check_referral_code(code=None):
	"""Lets the sign-in screen confirm a code before login. Yes/no only, and
	rate-limited so codes can't be enumerated."""
	return {"valid": engine.referral_code_exists(code)}


@frappe.whitelist(methods=["POST"])
def redeem(tier_id, country=None):
	user = _user()
	coupon = engine.redeem(user, tier_id, country)
	return {"coupon": coupon, "overview": engine.overview(user, country)}


@frappe.whitelist(methods=["POST"])
def redeem_to_wallet(points, country=None):
	user = _user()
	result = engine.convert_to_wallet(user, points)
	return {"wallet": result, "overview": engine.overview(user, country)}


@frappe.whitelist(methods=["POST"])
def create_topup(amount, country=None):
	"""Creates the Razorpay order for a wallet top-up (amount fixed here, server-side)."""
	return topup.create_topup(_user(), amount, country)


@frappe.whitelist(methods=["POST"])
def verify_topup(order_id, payment_id, signature, country=None):
	user = _user()
	result = topup.verify_topup(user, order_id, payment_id, signature)
	return {**result, "overview": engine.overview(user, country)}


@frappe.whitelist(methods=["GET"])
def get_points_history(page=1, page_size=20):
	return history.points_history(_user(), page, page_size)


@frappe.whitelist(methods=["GET"])
def get_wallet_history(page=1, page_size=20):
	return history.wallet_history(_user(), page, page_size)


@frappe.whitelist(methods=["GET"])
def get_invite_summary():
	return history.invite_summary(_user())


@frappe.whitelist(allow_guest=True, methods=["POST"])
def razorpay_webhook():
	"""Razorpay -> us. Authenticated by the HMAC signature, not a session."""
	request = frappe.request
	return topup.handle_webhook(request.get_data(), request.headers.get("X-Razorpay-Signature", ""))
