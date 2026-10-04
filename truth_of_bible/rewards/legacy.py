"""One-time move of members' old ERPNext wallet balances into the rewards
wallet, so the app has a single wallet.

The old wallet is the `User Wallet - TOB` account (credit − debit per
Customer — the same sum the old `get_customer_wallet_balance` server
script returns). For each member with money left there, the real run:

1. posts and submits a Journal Entry that empties the old wallet
   (debit `User Wallet - TOB` for that Customer, credit [contra_account]),
   so old screens (donations, send money) can't spend it a second time;
2. credits the same amount to the rewards wallet as an ADJUST row
   "Earlier wallet balance" (dedupe key `legacy_carryover`, so running
   this again skips members already moved).

Always look at the dry run first:

	bench --site <site> execute truth_of_bible.rewards.legacy.carry_over_wallets
	bench --site <site> execute truth_of_bible.rewards.legacy.carry_over_wallets \\
		--kwargs "{'dry_run': 0, 'contra_account': '<Account> - TOB'}"

[contra_account] is the account the moved liability is booked against —
an accounting choice, so it has no default.
"""

import frappe
from frappe.utils import flt, today

_OLD_WALLET = "User Wallet - TOB"
_COMPANY = "Truth of Bible"
_KEY = "legacy_carryover"


def _user_for(customer: str) -> str | None:
	"""The member a Customer belongs to: its email if that's a User, else
	the single User whose email starts with `<customer>@` (how the app
	names customers)."""
	email = frappe.db.get_value("Customer", customer, "email_id")
	if email and frappe.db.exists("User", email):
		return email
	matches = frappe.get_all("User", filters={"name": ["like", f"{customer}@%"]}, pluck="name", limit=2)
	return matches[0] if len(matches) == 1 else None


def _old_balances() -> list:
	return frappe.db.sql(
		"""select party, round(sum(credit) - sum(debit), 2) as balance
		from `tabGL Entry`
		where account = %s and party_type = 'Customer'
		group by party having balance > 0.004
		order by party""",
		_OLD_WALLET,
		as_dict=True,
	)


def carry_over_wallets(dry_run=1, contra_account=None) -> list:
	dry_run = str(dry_run) not in ("0", "false", "False")
	if not dry_run:
		if not contra_account or not frappe.db.exists("Account", contra_account):
			frappe.throw(f"Pass contra_account — an existing Account (got {contra_account!r}).")

	report = []
	for row in _old_balances():
		user = _user_for(row.party)
		entry = {"customer": row.party, "user": user, "amount": flt(row.balance)}
		if not user:
			entry["result"] = "skipped: no matching user"
		elif frappe.db.exists("TOB Reward Wallet Ledger", {"user": user, "dedupe_key": _KEY}):
			entry["result"] = "skipped: already moved"
		elif dry_run:
			entry["result"] = "would move"
		else:
			je = frappe.get_doc(
				{
					"doctype": "Journal Entry",
					"voucher_type": "Journal Entry",
					"company": _COMPANY,
					"posting_date": today(),
					"user_remark": f"Moved to the rewards wallet ({user})",
					"accounts": [
						{
							"account": _OLD_WALLET,
							"party_type": "Customer",
							"party": row.party,
							"debit_in_account_currency": entry["amount"],
						},
						{"account": contra_account, "credit_in_account_currency": entry["amount"]},
					],
				}
			)
			je.insert(ignore_permissions=True)
			je.submit()
			frappe.get_doc(
				{
					"doctype": "TOB Reward Wallet Ledger",
					"user": user,
					"kind": "ADJUST",
					"title": "Earlier wallet balance",
					"amount": entry["amount"],
					"dedupe_key": _KEY,
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()
			entry["result"] = f"moved ({je.name})"
		report.append(entry)

	for e in report:
		print(f"{e['customer']:<30} {str(e['user']):<40} {e['amount']:>10.2f}  {e['result']}")
	print(f"{len(report)} member(s); total {sum(e['amount'] for e in report):.2f}")
	return report


# --- old rewards (Customer Coupon) -> My Coupons ----------------------------

_STATUS = {"Redeemed": "USED", "Expired": "EXPIRED", "Available": "ACTIVE"}


def copy_old_rewards(dry_run=1) -> dict:
	"""Copies every old-system reward (Customer Coupon — quiz, verse, Sunday
	goal, group points...) into the member's My Coupons list as a CASH
	coupon, keeping its code, amount, type, dates and status (Redeemed ->
	USED, Expired -> EXPIRED, Available -> ACTIVE, or EXPIRED if its expiry
	has passed). The originals are not touched. Rows already copied are
	skipped, so this can be re-run.

	Copies are display records — redeemed ones were already paid into the
	old wallet (and that balance was moved by carry_over_wallets). Only an
	Available one can still be added to the wallet, from the app, once.

		bench --site <site> execute truth_of_bible.rewards.legacy.copy_old_rewards
		bench --site <site> execute truth_of_bible.rewards.legacy.copy_old_rewards --kwargs "{'dry_run': 0}"
	"""
	from frappe.utils import get_datetime, getdate, now_datetime

	dry_run = str(dry_run) not in ("0", "false", "False")
	users: dict[str, str | None] = {}
	summary: dict[str, dict] = {}
	skipped_no_user = 0
	today_ = getdate()
	for c in frappe.get_all(
		"Customer Coupon",
		fields=["name", "creation", "customer", "coupon_code", "expiry", "reward_amount", "status", "redeemed_on", "reward_type"],
		order_by="creation asc",
		limit_page_length=0,
	):
		if c.customer not in users:
			users[c.customer] = _user_for(c.customer)
		user = users[c.customer]
		if not user:
			skipped_no_user += 1
			continue
		row = summary.setdefault(user, {"USED": 0, "EXPIRED": 0, "ACTIVE": 0, "already": 0, "amount": 0.0})
		if frappe.db.exists("TOB Reward Coupon", {"legacy_coupon": c.name}):
			row["already"] += 1
			continue
		status = _STATUS.get(c.status, "EXPIRED")
		if status == "ACTIVE" and c.expiry and getdate(c.expiry) < today_:
			status = "EXPIRED"
		row[status] += 1
		row["amount"] += flt(c.reward_amount)
		if dry_run:
			continue
		amount = flt(c.reward_amount)
		doc = frappe.get_doc(
			{
				"doctype": "TOB Reward Coupon",
				"user": user,
				"kind": "CASH",
				"code": c.coupon_code or c.name,
				"tier": c.reward_type,
				"title": f"₹{amount:g} cash reward",
				"discount_label": c.reward_type or "Reward",
				"amount": amount,
				"status": status,
				"expires_on": get_datetime(f"{c.expiry} 23:59:00") if c.expiry else None,
				"used_on": c.redeemed_on,
				"legacy_coupon": c.name,
				"points_spent": 0,
			}
		).insert(ignore_permissions=True)
		# Keep the original date so the list sorts the way it happened.
		frappe.db.set_value("TOB Reward Coupon", doc.name, "creation", c.creation, update_modified=False)

	if not dry_run:
		frappe.db.commit()
	verb = "would copy" if dry_run else "copied"
	for user, r in sorted(summary.items()):
		print(
			f"{user:<40} {verb}: redeemed {r['USED']:>3}, expired {r['EXPIRED']:>3}, available {r['ACTIVE']:>2}"
			f"  (₹{r['amount']:g})  already copied {r['already']}"
		)
	totals = {k: sum(r[k] for r in summary.values()) for k in ("USED", "EXPIRED", "ACTIVE", "already")}
	print(f"{len(summary)} member(s); {verb} {totals['USED'] + totals['EXPIRED'] + totals['ACTIVE']} "
		f"(redeemed {totals['USED']}, expired {totals['EXPIRED']}, available {totals['ACTIVE']}); "
		f"already copied {totals['already']}; no matching user {skipped_no_user}")
	return {"members": len(summary), **totals, "no_user": skipped_no_user}


# --- past Sunday School redemptions / expiries -> My Coupons cards ----------


def backfill_sunday_school_cards(dry_run=1) -> dict:
	"""Adds the My Coupons card that newer code creates on every Sunday
	School redemption (green, Redeemed) and expiry (grey, Expired) for the
	ones that happened before that code existed. Skips any that already
	have a card (same member, same kind, same points, within two minutes),
	so it can be re-run safely.

	Amount: a redemption uses what actually reached the wallet (the wallet
	ledger row shares the Sunday School row's dedupe key); an expiry uses
	the current conversion rate.

		bench --site <site> execute truth_of_bible.rewards.legacy.backfill_sunday_school_cards
		bench --site <site> execute truth_of_bible.rewards.legacy.backfill_sunday_school_cards --kwargs "{'dry_run': 0}"
	"""
	from datetime import timedelta

	from frappe.utils import get_datetime

	from truth_of_bible.sunday_school import engine as sunday_school

	dry_run = str(dry_run) not in ("0", "false", "False")
	rate = flt(sunday_school.settings().wallet_conversion_rate) or 1
	report = {"redeemed": 0, "expired": 0, "already": 0, "amount": 0.0}
	for row in frappe.get_all(
		"TOB Sunday School Points Ledger",
		filters={"source": ["in", ["Redemption", "Expired"]], "points": ["<", 0]},
		fields=["name", "user", "source", "points", "dedupe_key", "creation"],
		order_by="creation asc",
		limit_page_length=0,
	):
		points = -int(row.points)
		status = "USED" if row.source == "Redemption" else "EXPIRED"
		at = get_datetime(row.creation)
		if frappe.db.exists(
			"TOB Reward Coupon",
			{
				"user": row.user,
				"tier": "Sunday School",
				"status": status,
				"points_spent": points,
				"creation": ["between", [at - timedelta(minutes=2), at + timedelta(minutes=2)]],
			},
		):
			report["already"] += 1
			continue

		amount = None
		if status == "USED" and row.dedupe_key:
			amount = frappe.db.get_value(
				"TOB Reward Wallet Ledger", {"user": row.user, "dedupe_key": row.dedupe_key}, "amount"
			)
		amount = round(flt(amount) if amount else points * rate, 2)
		report["redeemed" if status == "USED" else "expired"] += 1
		report["amount"] += amount
		print(f"{row.user:<40} {row.creation:%Y-%m-%d %H:%M}  {status:<8} {points:>4} pts  ₹{amount:g}")
		if dry_run:
			continue
		doc = frappe.get_doc(
			{
				"doctype": "TOB Reward Coupon",
				"user": row.user,
				"kind": "CASH",
				"code": f"SS-{row.name[:8].upper()}",
				"tier": "Sunday School",
				"title": f"₹{amount:g} cash reward",
				"discount_label": f"Sunday School reward · {points} points"
				if status == "USED"
				else f"Sunday School · {points} points expired",
				"amount": amount,
				"points_spent": points,
				"status": status,
				"used_on": row.creation if status == "USED" else None,
				"expires_on": row.creation if status == "EXPIRED" else None,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("TOB Reward Coupon", doc.name, "creation", row.creation, update_modified=False)

	if not dry_run:
		frappe.db.commit()
	verb = "would add" if dry_run else "added"
	print(
		f"{verb}: {report['redeemed']} redeemed + {report['expired']} expired card(s), "
		f"₹{report['amount']:g} in total; already had a card: {report['already']}"
	)
	return report


# --- old rewards -> Sunday School points history (one summary per student) --

_LEGACY_SS_KEY = "legacy-ss"


def _reward_types(value) -> list[str]:
	"""None / "all" = every type; else a comma list or a list."""
	if not value or (isinstance(value, str) and value.strip().lower() == "all"):
		return []
	if isinstance(value, str):
		return [t.strip() for t in value.split(",") if t.strip()]
	return [str(t).strip() for t in value if str(t).strip()]


def _half_up(x: float) -> int:
	"""838.50 -> 839 (Python's round() would send halves to the even number)."""
	return int(flt(x) + 0.5)


def old_sunday_school_points(reward_types="all", dry_run=1, list_types=0) -> dict:
	"""Shows each student's old-system rewards (Customer Coupon) in the
	Sunday School points history: the same figures as the Customer Coupon
	summary report (Total Reward / Redeemed / Available), as history only.

	List the old reward types:
		bench --site <site> execute truth_of_bible.rewards.legacy.old_sunday_school_points --kwargs "{'list_types': 1}"

	Preview, all types (nothing is written while dry_run is 1):
		bench --site <site> execute truth_of_bible.rewards.legacy.old_sunday_school_points

	Only some types:
		... --kwargs "{'reward_types': 'Sunday Goal Completed, Verse Studied'}"

	Write it:
		... --kwargs "{'dry_run': 0}"

	Points = rupees / Sunday School `wallet_conversion_rate` (rupees per
	point), taken on each student's TOTALS and rounded half up once (not per
	coupon), so they stay within half a point of the report.

	Per student, on their old reward dates, up to four ledger rows:
	  +earned     "Manual Adjustment"  "Earlier system rewards - N coupons"
	  -redeemed   "Redemption"         "Redeemed in earlier system"
	  -available  "Redemption"         "Moved to My Coupons" (redeemable there
	                                    once as cash cards - copy_old_rewards)
	  -expired    "Expired"            "Expired in earlier system"
	earned = redeemed + available + expired exactly, so the balance,
	leaderboards (no group), past group bonuses and the expiry clock don't
	change; the history header gains Earned / Redeemed / Expired. Students
	already done are skipped (dedupe key legacy-ss:<user>:earn), so re-runs
	are safe.
	"""
	from frappe.utils import get_datetime, getdate

	from truth_of_bible.sunday_school import engine as sunday_school

	dry_run = str(dry_run) not in ("0", "false", "False")

	if str(list_types) not in ("0", "false", "False", "None", ""):
		rows = frappe.db.sql(
			"""select coalesce(reward_type, '') as reward_type, status, count(*) as n,
				sum(reward_amount) as amount, count(distinct customer) as members
			from `tabCustomer Coupon` group by coalesce(reward_type, ''), status
			order by reward_type, status""",
			as_dict=True,
		)
		print(f"{'reward_type':<30} {'status':<10} {'count':>6} {'members':>8} {'total':>10}")
		for r in rows:
			print(f"{r.reward_type or '(blank)':<30} {r.status or '':<10} {r.n:>6} {r.members:>8} {flt(r.amount):>10.2f}")
		return {"reward_types": sorted({r.reward_type for r in rows})}

	types = _reward_types(reward_types)
	rate = flt(sunday_school.settings().wallet_conversion_rate) or 1
	today_ = getdate()
	filters = {"reward_type": ["in", types]} if types else {}

	students: dict[str, dict] = {}
	users: dict[str, str | None] = {}
	no_user: dict[str, float] = {}
	for c in frappe.get_all(
		"Customer Coupon",
		filters=filters,
		fields=["name", "creation", "customer", "expiry", "reward_amount", "status"],
		order_by="creation asc",
		limit_page_length=0,
	):
		if c.customer not in users:
			users[c.customer] = _user_for(c.customer)
		user = users[c.customer]
		amount = flt(c.reward_amount)
		if not user:
			no_user[c.customer] = no_user.get(c.customer, 0) + amount
			continue
		st = students.setdefault(
			user,
			{"customer": c.customer, "coupons": 0, "total": 0.0, "redeemed": 0.0, "available": 0.0, "first": c.creation, "last": c.creation},
		)
		st["coupons"] += 1
		st["total"] += amount
		st["last"] = c.creation
		if c.status == "Redeemed":
			st["redeemed"] += amount
		elif c.status == "Available" and not (c.expiry and getdate(c.expiry) < today_):
			st["available"] += amount

	report = []
	already = 0
	for user, st in sorted(students.items(), key=lambda kv: -kv[1]["total"]):
		earned = _half_up(st["total"] / rate)
		redeemed = _half_up(st["redeemed"] / rate)
		available = _half_up(st["available"] / rate)
		expired = max(0, earned - redeemed - available)  # remainder: rows always net to 0
		earn_key = f"{_LEGACY_SS_KEY}:{user}:earn"
		done = bool(frappe.db.exists("TOB Sunday School Points Ledger", {"user": user, "dedupe_key": earn_key}))
		if done:
			already += 1
		report.append((user, st, earned, redeemed, expired, available, done))
		if dry_run or done or earned <= 0:
			continue

		first, last = get_datetime(st["first"]), get_datetime(st["last"])
		rows = [
			("Manual Adjustment", f"Earlier system rewards - {st['coupons']} coupons", earned, earn_key, first),
			("Redemption", "Redeemed in earlier system", -redeemed, f"{_LEGACY_SS_KEY}:{user}:redeemed", last),
			("Redemption", "Moved to My Coupons", -available, f"{_LEGACY_SS_KEY}:{user}:available", last),
			("Expired", "Expired in earlier system", -expired, f"{_LEGACY_SS_KEY}:{user}:expired", last),
		]
		for source, title, pts, key, at in rows:
			if pts == 0:
				continue
			# Written directly, not via sunday_school.award(): award() would
			# start the expiry clock on the +earned row.
			doc = frappe.get_doc(
				{
					"doctype": "TOB Sunday School Points Ledger",
					"user": user,
					"week_start": sunday_school.week_start_of(getdate(at)),
					"source": source,
					"title": title,
					"points": pts,
					"group": None,  # no group: past group totals stay as they were
					"dedupe_key": key,
				}
			).insert(ignore_permissions=True)
			# Original dates: history sorts the way it happened, and the
			# "since last reset" history view isn't affected.
			frappe.db.set_value("TOB Sunday School Points Ledger", doc.name, "creation", at, update_modified=False)

	if not dry_run:
		frappe.db.commit()

	verb = "would add" if dry_run else "added"
	print(f"Rate {rate:g} per point - types: {', '.join(types) if types else 'all'}")
	print(f"{'customer':<26} {'user':<34} {'coupons':>7} {'total':>9} {'earned':>7} {'redeemed':>8} {'expired':>7} {'avail':>6}")
	for user, st, earned, redeemed, expired, available, done in report:
		flag = "  (already added)" if done else ""
		print(
			f"{str(st['customer'])[:26]:<26} {user[:34]:<34} {st['coupons']:>7} {st['total']:>9.2f} "
			f"{earned:>7} {redeemed:>8} {expired:>7} {available:>6}{flag}"
		)
	totals = {
		"earned": sum(r[2] for r in report),
		"redeemed": sum(r[3] for r in report),
		"expired": sum(r[4] for r in report),
		"available": sum(r[5] for r in report),
	}
	print(
		f"{len(report)} student(s) {verb}: earned {totals['earned']}, redeemed {totals['redeemed']}, "
		f"expired {totals['expired']}, moved to My Coupons {totals['available']} points. Balances unchanged. "
		f"Already added {already}."
	)
	if no_user:
		print(
			f"WARNING {len(no_user)} customer(s) have no matching app user (skipped): "
			+ ", ".join(f"{k} {v:g}" for k, v in sorted(no_user.items(), key=lambda kv: -kv[1])[:10])
		)
	return {"students": len(report), "already": already, "no_user": len(no_user), **totals}
