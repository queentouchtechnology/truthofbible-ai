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
