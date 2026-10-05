"""Journal notes can't be lost: one note per (user, plan, day), enforced by
the database, and saved under a per-user lock.

`ensure_unique_notes` runs after every migrate (hooks.py). It's safe to
repeat: it first MERGES any duplicate notes for the same day into one — the
texts are joined, oldest first, so no words are dropped — then adds the
unique index if it isn't there yet. (An after_migrate hook rather than a
patch: patches run before a brand-new doctype's table exists.)"""

import frappe

_DOCTYPE = "TOB Reading Plan Note"
_CONSTRAINT = "unique_user_plan_day"


def _index_exists() -> bool:
	return bool(frappe.db.sql(f"show index from `tab{_DOCTYPE}` where Key_name=%s", _CONSTRAINT))


def merge_duplicates() -> int:
	"""Folds every duplicated (user, plan, day) into its oldest row. Returns
	how many extra rows were merged away."""
	dupes = frappe.db.sql(
		f"""select user, plan, day_number from `tab{_DOCTYPE}`
		group by user, plan, day_number having count(*) > 1""",
		as_dict=True,
	)
	merged = 0
	for d in dupes:
		rows = frappe.db.sql(
			f"""select name, note from `tab{_DOCTYPE}`
			where user=%s and plan=%s and day_number=%s order by creation asc for update""",
			(d.user, d.plan, d.day_number),
			as_dict=True,
		)
		texts = []
		for r in rows:
			t = (r.note or "").strip()
			if t and t not in texts:
				texts.append(t)
		keep = rows[0].name
		frappe.db.set_value(_DOCTYPE, keep, "note", "\n\n".join(texts), update_modified=False)
		for r in rows[1:]:
			frappe.db.delete(_DOCTYPE, {"name": r.name})
			merged += 1
	return merged


def ensure_unique_notes() -> None:
	if not frappe.db.table_exists(_DOCTYPE):
		return
	merge_duplicates()
	frappe.db.commit()
	if not _index_exists():
		frappe.db.add_unique(_DOCTYPE, ["user", "plan", "day_number"], constraint_name=_CONSTRAINT)
		frappe.db.commit()
