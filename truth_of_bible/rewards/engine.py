"""Rewards: points earned automatically for real engagement with the Bible
app, spent on short-lived shop coupons. No manual approval anywhere — a
person can't be "approved" into points; the app's own activity earns them.

What earns points (all automatic, all capped so nothing can be farmed):

- Reading, quizzes, devotionals, prayer topics — awarded from the activity
  events the app already reports (analytics/activity.py calls
  `on_activity`), so there is no separate "claim" step and no way to claim
  something that didn't happen.
- Streak milestones — a daily-reading streak, celebrated at 3/7/14/30 days.
- Daily check-in, sharing the app (capped), completing the profile (once),
  and a completed shop order (from the WooCommerce webhook).

Deliberately NOT included: "follow on Instagram", "write a review" and
similar — they can't be verified from here, and an honour-system reward
teaches people to click through for points.

Every award goes through `_award`, whose `dedupe_key` (unique per user)
makes it idempotent: a retried request, a re-sent event or a double tap can
never pay twice.

Points can be spent two ways, both automatic:

- `redeem`: a real, global WooCommerce coupon for the Edenza shop (single
  use, short expiry, deliberately NOT tied to one email — a shopper may
  check out with a different address). Created FIRST; points are debited
  only if that succeeded, so a failure never costs anyone points.
- `convert_to_wallet`: points become wallet balance (an ERPNext Journal
  Entry crediting "User Wallet - TOB" for the user's Customer), which then
  pays for AI credits or anything else the wallet covers. The expense
  side is a configured account (`rewards_wallet_expense_account`) — never
  the Bank account the top-up flow uses, which would misstate the books.
"""

import secrets
from datetime import timedelta

import frappe
import requests
from frappe.utils import add_days, get_datetime, getdate, now_datetime, nowdate

_WC_BASE = "https://www.edenza.org/wp-json/wc/v3"
_TIMEOUT = 20

# code -> rule. per_day = max awards of this kind per calendar day.
RULES = {
	"daily_checkin": {"points": 1, "title": "Daily check-in", "per_day": 1},
	"read_chapter": {"points": 2, "title": "Read a Bible chapter", "per_day": 1, "event": "verse_opened"},
	"complete_quiz": {"points": 3, "title": "Completed a quiz", "per_day": 3, "event": "quiz_completed"},
	"devotional": {"points": 1, "title": "Read a devotional", "per_day": 1, "event": "devotional_viewed"},
	"prayer": {"points": 1, "title": "Explored a prayer topic", "per_day": 1, "event": "prayer_topic_explored"},
	"share_app": {"points": 1, "title": "Shared the app", "per_day": 3},
	"complete_profile": {"points": 2, "title": "Completed your profile", "once": True},
	"order": {"points": 20, "title": "Placed a shop order", "once_per_ref": True},
}
_EVENT_TO_RULE = {r["event"]: code for code, r in RULES.items() if r.get("event")}

# Streak length -> bonus. A streak counts days with a check-in or a chapter read.
STREAK_MILESTONES = ((3, 2), (7, 5), (14, 10), (30, 25))
_STREAK_REASONS = ("daily_checkin", "read_chapter")

# Coupon tiers — deliberately small and short-lived. Edit here (or override
# with `rewards_tiers` in site_config.json) to change the economics.
TIERS = (
	{"id": "save10", "points": 25, "percent": 10, "valid_days": 7},
	{"id": "save20", "points": 60, "percent": 20, "valid_days": 7},
	{"id": "save35", "points": 120, "percent": 35, "valid_days": 5},
)
MAX_ACTIVE_COUPONS = 3


def tiers():
	custom = frappe.get_site_config().get("rewards_tiers")
	return custom if isinstance(custom, list) and custom else list(TIERS)


def _today():
	return getdate(nowdate())


# --- ledger ------------------------------------------------------------


def balance(user: str) -> int:
	return int(frappe.db.sql("select coalesce(sum(points), 0) from `tabTOB Reward Ledger` where user=%s", user)[0][0])


def lifetime(user: str) -> int:
	return int(
		frappe.db.sql(
			"select coalesce(sum(points), 0) from `tabTOB Reward Ledger` where user=%s and points > 0", user
		)[0][0]
	)


def _award(user: str, code: str, points: int, title: str, dedupe_key: str) -> bool:
	"""True if points were actually granted (False = already granted)."""
	if frappe.db.exists("TOB Reward Ledger", {"user": user, "dedupe_key": dedupe_key}):
		return False
	frappe.get_doc(
		{
			"doctype": "TOB Reward Ledger",
			"user": user,
			"reason": code,
			"title": title,
			"points": points,
			"dedupe_key": dedupe_key,
		}
	).insert(ignore_permissions=True)
	return True


def _award_rule(user: str, code: str, day=None, ref: str | None = None) -> int:
	"""Awards a rule's points subject to its cap. Returns points granted."""
	rule = RULES[code]
	day = day or _today()
	if rule.get("once"):
		key = code
	elif rule.get("once_per_ref"):
		key = f"{code}:{ref}"
	else:
		n = int(
			frappe.db.count("TOB Reward Ledger", {"user": user, "reason": code, "dedupe_key": ["like", f"{code}:{day}:%"]})
		)
		if n >= rule.get("per_day", 1):
			return 0
		key = f"{code}:{day}:{n + 1}"
	if not _award(user, code, rule["points"], rule["title"], key):
		return 0
	granted = rule["points"]
	if code in _STREAK_REASONS:
		granted += _award_streak_milestone(user)
	return granted


# --- streaks -----------------------------------------------------------


def _active_days(user: str) -> set:
	rows = frappe.db.sql(
		"""select distinct date(creation) from `tabTOB Reward Ledger`
		where user=%s and reason in %s and creation >= %s""",
		(user, _STREAK_REASONS, add_days(_today(), -400)),
	)
	return {getdate(r[0]) for r in rows}


def streak(user: str) -> int:
	days = _active_days(user)
	today = _today()
	cursor = today if today in days else add_days(today, -1)
	count = 0
	while cursor in days:
		count += 1
		cursor = add_days(cursor, -1)
	return count


def _award_streak_milestone(user: str) -> int:
	current = streak(user)
	for length, bonus in STREAK_MILESTONES:
		if current == length:
			start = add_days(_today(), -(length - 1))
			if _award(user, f"streak_{length}", bonus, f"{length}-day streak bonus", f"streak_{length}:{start}"):
				return bonus
	return 0


# --- automatic earning -------------------------------------------------


def on_activity(user: str, event: str, event_time) -> None:
	"""Called for every recorded activity event (analytics/activity.py).
	Only today's events earn — a queue that flushes days late can't be used
	to back-fill points. Never raises into the activity logger."""
	code = _EVENT_TO_RULE.get(event)
	if not code:
		return
	day = getdate(event_time) if event_time else _today()
	if day != _today():
		return
	_award_rule(user, code, day)


def on_order_completed(user: str, order_id) -> None:
	_award_rule(user, "order", ref=str(order_id))


# --- explicit actions --------------------------------------------------


def check_in(user: str) -> dict:
	granted = _award_rule(user, "daily_checkin")
	return {"granted": granted, "already": granted == 0}


def record_share(user: str) -> dict:
	return {"granted": _award_rule(user, "share_app")}


def claim_profile(user: str) -> dict:
	row = frappe.db.get_value("User", user, ["first_name", "mobile_no"], as_dict=True) or {}
	if not (row.get("first_name") and row.get("mobile_no")):
		frappe.throw(
			frappe._("Add your name and mobile number in your profile first."), frappe.ValidationError
		)
	return {"granted": _award_rule(user, "complete_profile")}


# --- wallet ------------------------------------------------------------

_WALLET_ACCOUNT = "User Wallet - TOB"
_WALLET_COMPANY = "Truth of Bible"
_WALLET_MIN_POINTS = 20
_WALLET_PRESETS = (20, 50, 100)


def _wallet_config() -> dict:
	conf = frappe.get_site_config()
	return {
		"expense_account": conf.get("rewards_wallet_expense_account"),
		"rate": float(conf.get("rewards_wallet_rate") or 1),
		"company": conf.get("rewards_wallet_company") or _WALLET_COMPANY,
		"wallet_account": conf.get("rewards_wallet_account") or _WALLET_ACCOUNT,
	}


def wallet_options(bal: int) -> dict:
	cfg = _wallet_config()
	return {
		"enabled": bool(cfg["expense_account"]),
		"rate": cfg["rate"],
		"min_points": _WALLET_MIN_POINTS,
		"options": [
			{"points": p, "amount": round(p * cfg["rate"], 2), "affordable": bal >= p}
			for p in _WALLET_PRESETS
		],
	}


def _customer_for(user: str):
	"""The wallet is keyed by ERPNext Customer — named by the user's email
	in this app (see the wallet balance/top-up calls)."""
	if frappe.db.exists("Customer", user):
		return user
	email = frappe.db.get_value("User", user, "email")
	if email and frappe.db.exists("Customer", email):
		return email
	return frappe.db.get_value("Customer", {"email_id": email or user}, "name")


def convert_to_wallet(user: str, points: int) -> dict:
	cfg = _wallet_config()
	if not cfg["expense_account"]:
		frappe.throw(frappe._("Wallet conversion isn't available yet."), frappe.ValidationError)
	points = int(points)
	if points < _WALLET_MIN_POINTS:
		frappe.throw(
			frappe._("Convert at least {0} points at a time.").format(_WALLET_MIN_POINTS), frappe.ValidationError
		)
	if balance(user) < points:
		frappe.throw(frappe._("You don't have enough points for that."), frappe.ValidationError)
	customer = _customer_for(user)
	if not customer:
		frappe.throw(
			frappe._("Your wallet isn't set up yet. Open the wallet once, then try again."), frappe.ValidationError
		)
	amount = round(points * cfg["rate"], 2)

	# Credit the wallet FIRST; only take the points if that worked.
	try:
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"company": cfg["company"],
				"posting_date": nowdate(),
				"user_remark": f"Rewards: {points} points converted to wallet ({user})",
				"accounts": [
					{"account": cfg["expense_account"], "debit_in_account_currency": amount},
					{
						"account": cfg["wallet_account"],
						"party_type": "Customer",
						"party": customer,
						"credit_in_account_currency": amount,
					},
				],
			}
		)
		je.insert(ignore_permissions=True)
		je.submit()
	except Exception:
		frappe.log_error(title="Rewards: wallet credit failed", message=frappe.get_traceback())
		frappe.throw(
			frappe._("Couldn't add to your wallet right now. No points were spent."), frappe.ValidationError
		)

	frappe.get_doc(
		{
			"doctype": "TOB Reward Ledger",
			"user": user,
			"reason": "wallet",
			"title": f"Converted to ₹{amount:g} wallet balance",
			"points": -points,
			"dedupe_key": f"wallet:{je.name}",
		}
	).insert(ignore_permissions=True)
	return {"points": points, "amount": amount, "entry": je.name}


# --- coupons -----------------------------------------------------------


def _wc_auth():
	return frappe.get_site_config().get("woocommerce_api_auth")


def _tier(tier_id: str):
	return next((t for t in tiers() if t["id"] == tier_id), None)


def _discount_label(t: dict) -> str:
	return f"{t['percent']}% off at Edenza"


def redeem(user: str, tier_id: str) -> dict:
	tier = _tier(tier_id)
	if not tier:
		frappe.throw(frappe._("That reward isn't available."), frappe.ValidationError)
	if balance(user) < tier["points"]:
		frappe.throw(
			frappe._("You need {0} more points for this.").format(tier["points"] - balance(user)),
			frappe.ValidationError,
		)
	_expire_stale(user)
	active = frappe.db.count("TOB Reward Coupon", {"user": user, "status": "ACTIVE"})
	if active >= MAX_ACTIVE_COUPONS:
		frappe.throw(
			frappe._("You already have {0} unused coupons — use one before getting another.").format(active),
			frappe.ValidationError,
		)
	auth = _wc_auth()
	if not auth:
		frappe.throw(
			frappe._("Coupons aren't available right now. Please try again later."), frappe.ValidationError
		)

	code = "TOB" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(7))
	expires = (now_datetime() + timedelta(days=tier["valid_days"])).replace(hour=23, minute=59, second=0, microsecond=0)
	try:
		response = requests.post(
			f"{_WC_BASE}/coupons",
			headers={"Authorization": auth},
			json={
				"code": code,
				"discount_type": "percent",
				"amount": str(tier["percent"]),
				"date_expires": expires.strftime("%Y-%m-%dT%H:%M:%S"),
				"individual_use": True,
				"usage_limit": 1,
				"usage_limit_per_user": 1,
				"description": f"Truth of Bible rewards — {tier['points']} points ({user})",
			},
			timeout=_TIMEOUT,
		)
	except requests.RequestException:
		frappe.log_error(title="Rewards: coupon request failed", message=frappe.get_traceback())
		frappe.throw(frappe._("Couldn't create your coupon right now. No points were spent."), frappe.ValidationError)
	if response.status_code not in (200, 201):
		frappe.log_error(
			title="Rewards: coupon rejected by the shop",
			message=f"HTTP {response.status_code}: {response.text[:1500]}",
		)
		frappe.throw(frappe._("Couldn't create your coupon right now. No points were spent."), frappe.ValidationError)

	# The coupon exists — now, and only now, take the points.
	frappe.get_doc(
		{
			"doctype": "TOB Reward Ledger",
			"user": user,
			"reason": "redeem",
			"title": f"Redeemed for {tier['percent']}% off coupon",
			"points": -tier["points"],
			"dedupe_key": f"redeem:{code}",
		}
	).insert(ignore_permissions=True)
	doc = frappe.get_doc(
		{
			"doctype": "TOB Reward Coupon",
			"user": user,
			"code": code,
			"tier": tier["id"],
			"title": f"{tier['percent']}% off",
			"discount_label": _discount_label(tier),
			"points_spent": tier["points"],
			"expires_on": expires,
			"status": "ACTIVE",
			"wc_coupon_id": str((response.json() or {}).get("id") or ""),
		}
	)
	doc.insert(ignore_permissions=True)
	return _coupon_row(doc.as_dict())


def _expire_stale(user: str) -> None:
	frappe.db.sql(
		"update `tabTOB Reward Coupon` set status='EXPIRED' where user=%s and status='ACTIVE' and expires_on < %s",
		(user, now_datetime()),
	)


def _sync_used(user: str) -> None:
	"""Marks coupons the shop reports as used. Cached 10 minutes per coupon —
	this runs when the screen opens, and WooCommerce shouldn't be hit on
	every visit."""
	auth = _wc_auth()
	if not auth:
		return
	for c in frappe.get_all("TOB Reward Coupon", filters={"user": user, "status": "ACTIVE"}, fields=["name", "code"]):
		key = f"tob_reward_coupon_checked_{c.code}"
		if frappe.cache().get_value(key):
			continue
		try:
			r = requests.get(
				f"{_WC_BASE}/coupons", headers={"Authorization": auth}, params={"code": c.code}, timeout=_TIMEOUT
			)
			if r.status_code == 200 and r.json() and int(r.json()[0].get("usage_count") or 0) > 0:
				frappe.db.set_value("TOB Reward Coupon", c.name, "status", "USED")
			frappe.cache().set_value(key, 1, expires_in_sec=600)
		except requests.RequestException:
			continue


def _coupon_row(c) -> dict:
	expires = get_datetime(c.get("expires_on")) if c.get("expires_on") else None
	days_left = max(0, (expires - now_datetime()).days) if expires else 0
	return {
		"code": c.get("code"),
		"title": c.get("title"),
		"discount_label": c.get("discount_label"),
		"status": c.get("status"),
		"expires_on": str(expires) if expires else None,
		"days_left": days_left,
	}


# --- referrals (existing system, read-only) -----------------------------


def referral_overview(user: str):
	"""The person's standing in the EXISTING referral programme — their
	`Referral Profile` and the `Referral Tier` ladder. Read-only: referral
	points and payouts stay in that system (its own balance and screens);
	this only surfaces progress so the Rewards screen can point people at
	inviting friends. None if the programme doesn't exist for this person."""
	try:
		profile = frappe.db.get_value(
			"Referral Profile",
			{"user": user},
			["referral_code", "total_referrals", "current_tier", "available_points"],
			as_dict=True,
		)
		if not profile:
			return None
		ladder = frappe.get_all(
			"Referral Tier",
			filters={"active": 1},
			fields=["tier_name", "min_referrals", "max_referrals", "reward_per_friend", "description"],
			order_by="min_referrals asc",
		)
	except Exception:
		return None

	total = int(profile.total_referrals or 0)
	current = next((t for t in ladder if t.tier_name == profile.current_tier), None)
	upcoming = next((t for t in ladder if int(t.min_referrals or 0) > total), None)
	return {
		"code": profile.referral_code,
		"total_referrals": total,
		"tier": profile.current_tier,
		"reward_per_friend": int(current.reward_per_friend or 0) if current else 0,
		"available_points": int(profile.available_points or 0),
		"next_tier": upcoming.tier_name if upcoming else None,
		"friends_to_next_tier": max(0, int(upcoming.min_referrals) - total) if upcoming else 0,
		"next_reward_per_friend": int(upcoming.reward_per_friend or 0) if upcoming else 0,
	}


# --- the screen's data -------------------------------------------------


def overview(user: str) -> dict:
	_expire_stale(user)
	_sync_used(user)
	bal = balance(user)
	days = _active_days(user)
	today = _today()
	week = []
	for i in range(6, -1, -1):
		d = add_days(today, -i)
		week.append({"date": str(d), "label": d.strftime("%a")[0], "done": d in days, "today": d == today})

	def count_today(code):
		return int(
			frappe.db.count("TOB Reward Ledger", {"user": user, "reason": code, "dedupe_key": ["like", f"{code}:{today}:%"]})
		)

	profile_done = bool(frappe.db.exists("TOB Reward Ledger", {"user": user, "dedupe_key": "complete_profile"}))
	goals = [
		{"key": "daily_checkin", "title": "Daily check-in", "subtitle": "Tap to check in", "points": 1,
		 "done": count_today("daily_checkin") >= 1, "kind": "action", "progress": None},
		{"key": "read_chapter", "title": "Read a Bible chapter", "subtitle": "Counts automatically", "points": 2,
		 "done": count_today("read_chapter") >= 1, "kind": "auto", "progress": None},
		{"key": "complete_quiz", "title": "Complete a quiz", "subtitle": "Up to 3 a day", "points": 3,
		 "done": count_today("complete_quiz") >= 3, "kind": "auto", "progress": f"{count_today('complete_quiz')}/3"},
		{"key": "devotional", "title": "Read a devotional", "subtitle": "Counts automatically", "points": 1,
		 "done": count_today("devotional") >= 1, "kind": "auto", "progress": None},
		{"key": "share_app", "title": "Share the app", "subtitle": "Up to 3 a day", "points": 1,
		 "done": count_today("share_app") >= 3, "kind": "action", "progress": f"{count_today('share_app')}/3"},
	]
	if not profile_done:
		goals.append({"key": "complete_profile", "title": "Complete your profile", "subtitle": "One time",
			"points": 2, "done": False, "kind": "action", "progress": None})

	current = streak(user)
	milestones = [{"days": d, "points": p, "reached": current >= d} for d, p in STREAK_MILESTONES]

	tier_rows = []
	for t in tiers():
		tier_rows.append({
			"id": t["id"],
			"points": t["points"],
			"discount_label": _discount_label(t),
			"percent": t["percent"],
			"valid_days": t["valid_days"],
			"affordable": bal >= t["points"],
			"points_needed": max(0, t["points"] - bal),
		})
	next_tier = next((t for t in tier_rows if not t["affordable"]), None)

	coupons = frappe.get_all(
		"TOB Reward Coupon",
		filters={"user": user},
		fields=["code", "title", "discount_label", "status", "expires_on"],
		order_by="creation desc",
		limit_page_length=10,
	)
	history = frappe.get_all(
		"TOB Reward Ledger",
		filters={"user": user},
		fields=["title", "points", "creation"],
		order_by="creation desc",
		limit_page_length=15,
	)
	return {
		"balance": bal,
		"lifetime": lifetime(user),
		"streak": {
			"current": current,
			"checked_in_today": count_today("daily_checkin") >= 1,
			"week": week,
		},
		"goals": goals,
		"milestones": milestones,
		"tiers": tier_rows,
		"next_tier": next_tier,
		"wallet": wallet_options(bal),
		"referral": referral_overview(user),
		"coupons": [_coupon_row(c) for c in coupons],
		"history": [{"title": h.title, "points": h.points, "when": str(h.creation)} for h in history],
	}
