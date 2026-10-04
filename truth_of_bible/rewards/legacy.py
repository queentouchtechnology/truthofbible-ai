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


# --- old Sunday School rewards -> Sunday School points history -------------

_LEGACY_SS_KEY = "legacy-ss"


def _reward_types(value) -> list[str]:
	if not value:
		return []
	if isinstance(value, str):
		return [t.strip() for t in value.split(",") if t.strip()]
	return [str(t).strip() for t in value if str(t).strip()]


def old_sunday_school_points(reward_types=None, dry_run=1) -> dict:
	"""Shows old-system Sunday School rewards (Customer Coupon) in the
	Sunday School points history, as history only.

	Step 1 — which old reward types are Sunday School? Run without
	reward_types: it lists every old reward_type with counts and totals.

		bench --site <site> execute truth_of_bible.rewards.legacy.old_sunday_school_points

	Step 2 — preview the points per member for the chosen types (nothing
	is written while dry_run is 1):

		bench --site <site> execute truth_of_bible.rewards.legacy.old_sunday_school_points \
			--kwargs "{'reward_types': 'Sunday Goal, Weekly Quiz'}"

	Step 3 — write them:

		... --kwargs "{'reward_types': 'Sunday Goal, Weekly Quiz', 'dry_run': 0}"

	Points = the old ₹ amount ÷ Sunday School `wallet_conversion_rate` (₹ per
	point — the rate a redemption uses today), rounded.

	Each old reward becomes TWO ledger rows on its original date, so the
	balance, leaderboards, group totals and expiry clock don't change:
	  +points  "Manual Adjustment"  "Earlier system · <type>"
	  −points  closing row by the old status:
	           Redeemed  -> "Redemption"  (already paid in the old wallet)
	           Expired   -> "Expired"
	           Available -> "Redemption"  "Moved to My Coupons" — it is
	                         redeemable there once, as a cash card (see
	                         copy_old_rewards), never from the points balance.
	The history header then shows them in Earned / Redeemed / Expired.
	Skips rewards already written (dedupe keys legacy-ss:<coupon>:…), so it
	can be re-run.
	"""
	from frappe.utils import get_datetime, getdate

	from truth_of_bible.sunday_school import engine as sunday_school

	dry_run = str(dry_run) not in ("0", "false", "False")
	types = _reward_types(reward_types)

	if not types:
		rows = frappe.db.sql(
			"""select coalesce(reward_type, '') as reward_type, status, count(*) as n,
				sum(reward_amount) as amount, count(distinct customer) as members
			from `tabCustomer Coupon` group by coalesce(reward_type, ''), status
			order by reward_type, status""",
			as_dict=True,
		)
		print(f"{'reward_type':<30} {'status':<10} {'count':>6} {'members':>8} {'total ₹':>10}")
		for r in rows:
			print(f"{r.reward_type or '(blank)':<30} {r.status or '':<10} {r.n:>6} {r.members:>8} {flt(r.amount):>10.2f}")
		print("Pick the Sunday School ones and run again with reward_types.")
		return {"reward_types": sorted({r.reward_type for r in rows})}

	rate = flt(sunday_school.settings().wallet_conversion_rate) or 1
	today_ = getdate()
	users: dict[str, str | None] = {}
	per_user: dict[str, dict] = {}
	skipped_no_user = 0
	already = 0
	unconvertible = []  # amounts that aren't a whole number of points at this rate

	for c in frappe.get_all(
		"Customer Coupon",
		filters={"reward_type": ["in", types]},
		fields=["name", "creation", "customer", "coupon_code", "expiry", "reward_amount", "status", "reward_type"],
		order_by="creation asc",
		limit_page_length=0,
	):
		if c.customer not in users:
			users[c.customer] = _user_for(c.customer)
		user = users[c.customer]
		if not user:
			skipped_no_user += 1
			continue
		earn_key = f"{_LEGACY_SS_KEY}:{c.name}:earn"
		if frappe.db.exists("TOB Sunday School Points Ledger", {"user": user, "dedupe_key": earn_key}):
			already += 1
			continue

		amount = flt(c.reward_amount)
		exact = amount / rate
		points = int(round(exact))
		if abs(exact - points) > 0.01:
			unconvertible.append((user, c.name, amount))
		if points <= 0:
			continue

		status = c.status
		if status == "Available" and c.expiry and getdate(c.expiry) < today_:
			status = "Expired"
		if status == "Redeemed":
			close_source, close_title, bucket = "Redemption", f"Paid out in earlier system (₹{amount:g})", "redeemed"
		elif status == "Available":
			close_source, close_title, bucket = "Redemption", f"Moved to My Coupons as ₹{amount:g} cash reward", "my_coupons"
		else:
			close_source, close_title, bucket = "Expired", "Expired in earlier system", "expired"

		row = per_user.setdefault(user, {"earned": 0, "redeemed": 0, "expired": 0, "my_coupons": 0, "amount": 0.0, "rewards": 0})
		row["earned"] += points
		row[bucket] += points
		row["amount"] += amount
		row["rewards"] += 1
		if dry_run:
			continue

		at = get_datetime(c.creation)
		week = sunday_school.week_start_of(getdate(at))
		# Written directly, not via sunday_school.award(): award() would start
		# the expiry clock on the +points row.
		for source, title, pts, key in (
			("Manual Adjustment", f"Earlier system · {c.reward_type}", points, earn_key),
			(close_source, close_title, -points, f"{_LEGACY_SS_KEY}:{c.name}:close"),
		):
			doc = frappe.get_doc(
				{
					"doctype": "TOB Sunday School Points Ledger",
					"user": user,
					"week_start": week,
					"source": source,
					"title": title,
					"points": pts,
					"group": None,  # no group: past group totals stay as they were
					"dedupe_key": key,
				}
			).insert(ignore_permissions=True)
			# Original date, so history sorts the way it happened and the
			# "since last reset" history view isn't affected.
			frappe.db.set_value("TOB Sunday School Points Ledger", doc.name, "creation", at, update_modified=False)

	if not dry_run:
		frappe.db.commit()

	verb = "would add" if dry_run else "added"
	print(f"Rate: ₹{rate:g} per point. Types: {', '.join(types)}")
	print(f"{'member':<40} {'rewards':>7} {'₹':>9} {'earned':>7} {'redeemed':>8} {'expired':>7} {'MyCoupons':>9}")
	for user, r in sorted(per_user.items()):
		print(
			f"{user:<40} {r['rewards']:>7} {r['amount']:>9.2f} {r['earned']:>7} {r['redeemed']:>8} {r['expired']:>7} {r['my_coupons']:>9}"
		)
	totals = {k: sum(r[k] for r in per_user.values()) for k in ("rewards", "amount", "earned", "redeemed", "expired", "my_coupons")}
	print(
		f"{len(per_user)} member(s) {verb}: {totals['rewards']} rewards, ₹{totals['amount']:g} = {totals['earned']} points "
		f"(redeemed {totals['redeemed']}, expired {totals['expired']}, in My Coupons {totals['my_coupons']}). "
		f"Available balance unchanged. Already added {already}; no matching user {skipped_no_user}."
	)
	if unconvertible:
		print(f"⚠ {len(unconvertible)} reward(s) aren't a whole number of points at ₹{rate:g}/point (rounded), e.g. {unconvertible[:3]}")
	return {"members": len(per_user), "already": already, "no_user": skipped_no_user, "unconvertible": len(unconvertible), **totals}
