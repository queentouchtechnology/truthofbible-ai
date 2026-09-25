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
	if _award_rule(user, code, day) and code in ("read_chapter", "complete_quiz"):
		_settle_referral(user)


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
# The rewards wallet is its own ledger (TOB Reward Wallet Ledger) — it does
# not touch ERPNext accounts or the older wallet. It is kept in ONE base
# currency (`rewards_wallet_currency`, default INR — the Razorpay currency)
# and the app formats it, so it stays usable for every country.

_WALLET_MIN_POINTS = 20
_WALLET_PRESETS = (20, 50, 100)


def _wallet_config() -> dict:
	conf = frappe.get_site_config()
	return {
		"rate": float(conf.get("rewards_wallet_rate") or 0.5),
		"currency": conf.get("rewards_wallet_currency") or "INR",
		"enabled": conf.get("rewards_wallet_enabled", 1) not in (0, False, "0"),
	}


def wallet_balance(user: str) -> float:
	return round(
		float(frappe.db.sql("select coalesce(sum(amount), 0) from `tabTOB Reward Wallet Ledger` where user=%s", user)[0][0]),
		2,
	)


def wallet_options(user: str, bal: int) -> dict:
	cfg = _wallet_config()
	return {
		"enabled": cfg["enabled"],
		"currency": cfg["currency"],
		"rate": cfg["rate"],
		"balance": wallet_balance(user),
		"min_points": _WALLET_MIN_POINTS,
		"options": [
			{"points": p, "amount": round(p * cfg["rate"], 2), "affordable": bal >= p} for p in _WALLET_PRESETS
		],
	}


def convert_to_wallet(user: str, points: int) -> dict:
	cfg = _wallet_config()
	if not cfg["enabled"]:
		frappe.throw(frappe._("Wallet conversion isn't available yet."), frappe.ValidationError)
	points = int(points)
	if points < _WALLET_MIN_POINTS:
		frappe.throw(
			frappe._("Convert at least {0} points at a time.").format(_WALLET_MIN_POINTS), frappe.ValidationError
		)
	if balance(user) < points:
		frappe.throw(frappe._("You don't have enough points for that."), frappe.ValidationError)
	amount = round(points * cfg["rate"], 2)
	key = f"convert:{secrets.token_hex(6)}"
	# Points out and wallet in in one request — an error rolls both back.
	frappe.get_doc(
		{
			"doctype": "TOB Reward Ledger",
			"user": user,
			"reason": "wallet",
			"title": f"Converted to {cfg['currency']} {amount:g} wallet balance",
			"points": -points,
			"dedupe_key": key,
		}
	).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "TOB Reward Wallet Ledger",
			"user": user,
			"kind": "CONVERT",
			"title": f"{points} points converted",
			"amount": amount,
			"dedupe_key": key,
		}
	).insert(ignore_permissions=True)
	return {"points": points, "amount": amount, "currency": cfg["currency"]}


def wallet_spend(user: str, amount: float, title: str, ref: str) -> bool:
	"""Debits the wallet (e.g. for AI usage). False if the balance can't
	cover it. Idempotent per `ref`."""
	key = f"spend:{ref}"
	if frappe.db.exists("TOB Reward Wallet Ledger", {"user": user, "dedupe_key": key}):
		return True
	if wallet_balance(user) < amount:
		return False
	frappe.get_doc(
		{
			"doctype": "TOB Reward Wallet Ledger",
			"user": user,
			"kind": "SPEND",
			"title": title,
			"amount": -abs(amount),
			"dedupe_key": key,
		}
	).insert(ignore_permissions=True)
	return True


# --- coupons -----------------------------------------------------------


def _wc_auth():
	return frappe.get_site_config().get("woocommerce_api_auth")


def _tier(tier_id: str):
	return next((t for t in tiers() if t["id"] == tier_id), None)


def shop_available(country: str | None, user: str | None = None) -> bool:
	"""The Edenza shop ships in India only. `country` is the device region
	the app reports; failing that, an Indian mobile number decides. With no
	signal we assume India (where nearly all members are) — the coupon is
	only usable at the Indian shop either way."""
	country = (country or "").strip().upper()
	if country:
		return country == "IN"
	mobile = (frappe.db.get_value("User", user, "mobile_no") or "") if user else ""
	if mobile:
		digits = mobile.strip()
		return digits.startswith("+91") or digits.startswith("91") or (len(digits) == 10 and digits.isdigit())
	return True


def _discount_label(t: dict) -> str:
	return f"{t['percent']}% off at Edenza"


def redeem(user: str, tier_id: str, country: str | None = None) -> dict:
	if not shop_available(country, user):
		frappe.throw(
			frappe._("Shop coupons are for members in India. Convert your points to wallet balance instead."),
			frappe.ValidationError,
		)
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


# --- referrals ----------------------------------------------------------
# Self-contained (TOB Reward Profile / TOB Reward Referral); the older
# Referral Profile data is left untouched. Entering a code earns nothing by
# itself — the referral stays PENDING until the friend really starts reading,
# so throwaway accounts can't farm points.

REFERRER_POINTS = 5
FRIEND_POINTS = 2
REFERRER_MONTHLY_CAP = 20  # rewarded friends per calendar month
REFERRAL_MILESTONES = ((3, 5), (10, 15), (25, 40))  # rewarded friends -> bonus
_CLAIM_WINDOW_DAYS = 30  # only fairly new accounts can enter a code
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def referral_code(user: str) -> str:
	code = frappe.db.get_value("TOB Reward Profile", {"user": user}, "referral_code")
	if code:
		return code
	for _ in range(8):
		code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
		if not frappe.db.exists("TOB Reward Profile", {"referral_code": code}):
			frappe.get_doc({"doctype": "TOB Reward Profile", "user": user, "referral_code": code}).insert(
				ignore_permissions=True
			)
			return code
	frappe.throw(frappe._("Couldn't create your invite code. Please try again."), frappe.ValidationError)


def claim_referral(user: str, code: str) -> dict:
	code = (code or "").strip().upper()
	if not code:
		frappe.throw(frappe._("Enter your friend's invite code."), frappe.ValidationError)
	if frappe.db.exists("TOB Reward Referral", {"referee": user}):
		frappe.throw(frappe._("You've already used an invite code."), frappe.ValidationError)
	referrer = frappe.db.get_value("TOB Reward Profile", {"referral_code": code}, "user")
	if not referrer:
		frappe.throw(frappe._("That invite code isn't valid."), frappe.ValidationError)
	if referrer == user:
		frappe.throw(frappe._("You can't use your own code."), frappe.ValidationError)
	created = frappe.db.get_value("User", user, "creation")
	if created and (now_datetime() - get_datetime(created)).days > _CLAIM_WINDOW_DAYS:
		frappe.throw(frappe._("Invite codes are for new members (first 30 days)."), frappe.ValidationError)
	frappe.get_doc(
		{"doctype": "TOB Reward Referral", "referrer": referrer, "referee": user, "code": code, "status": "PENDING"}
	).insert(ignore_permissions=True)
	# If they've already been reading, pay out right away.
	return {"accepted": True, "friend_points": _settle_referral(user)}


def _settle_referral(user: str) -> int:
	"""Pays out a PENDING referral once the friend shows real activity.
	Returns the points the friend received (0 if nothing settled)."""
	row = frappe.db.get_value(
		"TOB Reward Referral", {"referee": user, "status": "PENDING"}, ["name", "referrer"], as_dict=True
	)
	if not row:
		return 0
	# Real activity = a chapter read or quiz done (not just a check-in tap).
	if not frappe.db.exists("TOB Reward Ledger", {"user": user, "reason": ["in", ["read_chapter", "complete_quiz"]]}):
		return 0
	month_start = getdate(nowdate()).replace(day=1)
	rewarded_this_month = frappe.db.count(
		"TOB Reward Referral", {"referrer": row.referrer, "status": "REWARDED", "rewarded_at": [">=", month_start]}
	)
	if rewarded_this_month >= REFERRER_MONTHLY_CAP:
		frappe.db.set_value("TOB Reward Referral", row.name, "status", "CAPPED")
	else:
		frappe.db.set_value("TOB Reward Referral", row.name, {"status": "REWARDED", "rewarded_at": now_datetime()})
		_award(row.referrer, "referral", REFERRER_POINTS, "A friend you invited started reading", f"referral:{user}")
		total = frappe.db.count("TOB Reward Referral", {"referrer": row.referrer, "status": "REWARDED"})
		for friends, bonus in REFERRAL_MILESTONES:
			if total == friends:
				_award(row.referrer, f"referral_{friends}", bonus, f"{friends} friends joined — bonus", f"referral_ms:{friends}")
	granted = _award(user, "referral_welcome", FRIEND_POINTS, "Welcome bonus — invited by a friend", "referral_welcome")
	return FRIEND_POINTS if granted else 0


def referral_overview(user: str) -> dict:
	code = referral_code(user)
	rewarded = frappe.db.count("TOB Reward Referral", {"referrer": user, "status": ["in", ["REWARDED", "CAPPED"]]})
	pending = frappe.db.count("TOB Reward Referral", {"referrer": user, "status": "PENDING"})
	earned = int(
		frappe.db.sql(
			"select coalesce(sum(points),0) from `tabTOB Reward Ledger` where user=%s and reason like 'referral%%'",
			user,
		)[0][0]
	)
	upcoming = next(((f, b) for f, b in REFERRAL_MILESTONES if f > rewarded), None)
	used_code = bool(frappe.db.exists("TOB Reward Referral", {"referee": user}))
	return {
		"code": code,
		"friends_rewarded": rewarded,
		"friends_pending": pending,
		"points_earned": earned,
		"per_friend": REFERRER_POINTS,
		"friend_gets": FRIEND_POINTS,
		"can_enter_code": not used_code,
		"next_milestone": (
			{"friends": upcoming[0], "bonus": upcoming[1], "remaining": upcoming[0] - rewarded} if upcoming else None
		),
		"milestones": [{"friends": f, "bonus": b, "reached": rewarded >= f} for f, b in REFERRAL_MILESTONES],
	}


# --- the screen's data -------------------------------------------------


def overview(user: str, country: str | None = None) -> dict:
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
		"shop_available": shop_available(country, user),
		"tiers": tier_rows,
		"next_tier": next_tier,
		"wallet": wallet_options(user, bal),
		"referral": referral_overview(user),
		"coupons": [_coupon_row(c) for c in coupons],
		"history": [{"title": h.title, "points": h.points, "when": str(h.creation)} for h in history],
	}
