"""Database-level guarantee that a reward credit is applied once.

The rewards code already serialises credits per member (`_lock_user`) and
checks `dedupe_key` before inserting, but that only holds while every code
path remembers to do both — a TOPUP for one Razorpay payment was credited
twice (verify call + webhook) before the lock existed. A unique index on
(user, dedupe_key) makes the database refuse a second row no matter which
path writes it.

Per user, not global: points keys like `daily_checkin:2026-09-26:1` are
shared by every member who checked in that day. NULL keys stay allowed
(MariaDB treats NULLs as distinct).

Stops the migration, listing the offenders, if a member already has a
duplicated key — those need a manual decision (which row to keep), not a
silent delete here."""

import frappe

_LEDGERS = ("TOB Reward Ledger", "TOB Reward Wallet Ledger")
_CONSTRAINT = "unique_user_dedupe_key"


def execute():
	for doctype in _LEDGERS:
		if not frappe.db.table_exists(doctype):
			continue
		dupes = frappe.db.sql(
			f"""select user, dedupe_key, count(*) as n from `tab{doctype}`
			where dedupe_key is not null and dedupe_key != ''
			group by user, dedupe_key having count(*) > 1""",
			as_dict=True,
		)
		if dupes:
			listing = "\n".join(f"  {d.user}  {d.dedupe_key}  x{d.n}" for d in dupes[:50])
			raise Exception(
				f"{doctype} has members with a duplicated dedupe_key — resolve these before migrating:\n{listing}"
			)
		# Blank keys would collide under the index; make them NULL.
		frappe.db.sql(f"update `tab{doctype}` set dedupe_key = null where dedupe_key = ''")
		frappe.db.add_unique(doctype, ["user", "dedupe_key"], constraint_name=_CONSTRAINT)
