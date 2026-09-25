"""Optional wallet charge for AI Q&A — OFF by default (AI stays free).

Turn on in site_config.json:
  rewards_ai_charge_enabled: 1
  rewards_ai_free_per_day:   3     (questions per day before the wallet is used)
  rewards_ai_cost:           1     (wallet-currency units per extra question)

A member out of free questions with too little wallet balance gets a clear
message instead of an answer; the wallet is debited only after the answer
succeeded."""

import functools

import frappe
from frappe.utils import nowdate

from truth_of_bible.rewards import engine


def charge_ai(fn):
	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		conf = frappe.get_site_config()
		user = frappe.session.user
		if not conf.get("rewards_ai_charge_enabled") or user in ("Guest", "Administrator"):
			return fn(*args, **kwargs)

		free = int(conf.get("rewards_ai_free_per_day") or 3)
		cost = float(conf.get("rewards_ai_cost") or 1)
		used = frappe.db.count(
			"TOB Bible Conversation Message", {"owner": user, "role": "user", "creation": [">=", nowdate()]}
		)
		paid = used >= free
		if paid and engine.wallet_balance(user) < cost:
			frappe.throw(
				frappe._("You've used today's free questions. Earn points and convert them to wallet balance to ask more."),
				frappe.ValidationError,
			)
		result = fn(*args, **kwargs)
		if paid:
			engine.wallet_spend(user, cost, "AI question", frappe.generate_hash(length=10))
		return result

	return wrapper
