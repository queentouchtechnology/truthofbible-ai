"""Whitelisted endpoints for the Rewards screen. Session-cookie auth — the
logged-in user's own session, never a client-supplied user id, exactly like
`analytics.record_batch`: points must only ever move for the person who
earned them."""

import frappe

from truth_of_bible.rewards import engine


def _user() -> str:
	user = frappe.session.user
	if user in ("Guest", "Administrator"):
		frappe.throw(frappe._("Please log in to use rewards."), frappe.PermissionError)
	return user


@frappe.whitelist(methods=["GET"])
def get_rewards():
	return engine.overview(_user())


@frappe.whitelist(methods=["POST"])
def check_in():
	user = _user()
	result = engine.check_in(user)
	return {**result, "overview": engine.overview(user)}


@frappe.whitelist(methods=["POST"])
def record_share():
	user = _user()
	result = engine.record_share(user)
	return {**result, "overview": engine.overview(user)}


@frappe.whitelist(methods=["POST"])
def claim_profile():
	user = _user()
	result = engine.claim_profile(user)
	return {**result, "overview": engine.overview(user)}


@frappe.whitelist(methods=["POST"])
def redeem(tier_id):
	user = _user()
	coupon = engine.redeem(user, tier_id)
	return {"coupon": coupon, "overview": engine.overview(user)}


@frappe.whitelist(methods=["POST"])
def redeem_to_wallet(points):
	user = _user()
	result = engine.convert_to_wallet(user, points)
	return {"wallet": result, "overview": engine.overview(user)}
