"""Sunday School weekly rewards — admin/teacher write actions that don't
fit generic `/api/resource/<Doctype>` REST (bulk roster save, verification
that must run through the scoring engine, manual quiz finalize/weekly
reset). Simple CRUD (Groups, Weekly Quiz, Weekly Quiz Question, Memory
Verse) is handled by the Flutter admin app hitting generic REST directly
with `erpToken`, same as `TOB Encouragement Message` — no wrapper needed
for those.
"""

import json

import frappe
from frappe import _
from frappe.utils import getdate

from truth_of_bible.communication.auth import require_admin
from truth_of_bible.sunday_school import engine


@frappe.whitelist(methods=["POST"])
def mark_attendance(week_start, entries):
	"""entries: JSON list of {"user": ..., "attended_class": bool, "attended_quiz": bool}
	— a full roster save for one week. Never touches completed_memory_verse
	(engine-owned, set only via verify_verse_completion)."""
	require_admin()
	week = getdate(week_start)
	if isinstance(entries, str):
		entries = json.loads(entries)

	updated = []
	for entry in entries:
		user = entry.get("user")
		if not user:
			continue
		attendance = engine.ensure_attendance(user, week)
		attendance.attended_class = 1 if entry.get("attended_class") else 0
		attendance.attended_quiz = 1 if entry.get("attended_quiz") else 0
		attendance.save(ignore_permissions=True)
		engine.check_sunday_goal(user, week)
		updated.append(user)

	frappe.db.commit()
	return {"updated": updated}


@frappe.whitelist(methods=["GET"])
def get_pending_verse_completions(memory_verse=None):
	require_admin()
	filters = {"status": "Pending"}
	if memory_verse:
		filters["memory_verse"] = memory_verse
	rows = frappe.get_all(
		"TOB Sunday School Verse Completion", filters=filters,
		fields=["name", "memory_verse", "user", "completed_at"], order_by="completed_at asc",
	)
	if rows:
		brief = {
			u.name: u.full_name
			for u in frappe.get_all("User", filters={"name": ["in", [r.user for r in rows]]}, fields=["name", "full_name"])
		}
		for r in rows:
			r["full_name"] = brief.get(r.user, r.user)
	return {"rows": rows}


@frappe.whitelist(methods=["POST"])
def verify_verse_completion(completion, verified, rank=None):
	require_admin()
	verified = str(verified).lower() in ("1", "true", "yes")
	rank = int(rank) if rank not in (None, "", "null") else None
	return engine.verify_verse_completion(completion, verified, rank)


@frappe.whitelist(methods=["POST"])
def finalize_quiz(quiz):
	require_admin()
	quiz_doc = frappe.get_doc("TOB Sunday School Weekly Quiz", quiz)
	if quiz_doc.status == "Closed":
		frappe.throw(_("This quiz is already closed."), frappe.ValidationError)
	return engine.finalize_quiz(quiz)


@frappe.whitelist(methods=["POST"])
def run_weekly_reset(week_start=None):
	"""Manual trigger for the same computation the Monday cron runs
	(notifications/sunday_school.py::weekly_reset_scan) — lets an admin
	force it early for testing or a missed run."""
	require_admin()
	from truth_of_bible.notifications.sunday_school import run_reset_for_week

	week = getdate(week_start) if week_start else engine.week_start_of()
	return run_reset_for_week(week)


@frappe.whitelist(methods=["POST"])
def mark_group_winner(week_start=None):
	"""Computes and awards just this week's (or a given week's) Group
	Bonus — the top-scoring group's members each get their own best quiz
	score ÷ group_bonus_divisor (see sunday_school/engine.py::
	compute_weekly_group_bonus). Deliberately lighter than run_weekly_reset:
	no quiz finalization, no SS_WEEKLY_RESULTS notification blast — lets an
	admin award/re-check the winner mid-week without triggering the full
	reset. Safe to call more than once for the same week (award() is
	idempotent via its own dedupe_key)."""
	require_admin()
	week = getdate(week_start) if week_start else engine.week_start_of()
	return engine.compute_weekly_group_bonus(week)


@frappe.whitelist(methods=["POST"])
def add_manual_points(user, points, title=None, week_start=None):
	"""A deliberate one-off admin entry (bonus, correction, penalty —
	`points` may be negative) — always creates its own ledger row (a
	fresh, random dedupe_key) rather than the "same trigger, same key"
	idempotency every other award() caller relies on, since a human
	choosing to award points twice means two real awards, not a retry."""
	require_admin()
	points = int(points)
	if points == 0:
		frappe.throw(_("Points must not be zero."), frappe.ValidationError)
	week = getdate(week_start) if week_start else engine.week_start_of()
	title = title or ("Manual point adjustment" if points > 0 else "Manual point deduction")
	dedupe_key = f"manual:{frappe.generate_hash(length=12)}"
	awarded = engine.award(user, "Manual Adjustment", title, points, week_start=week, dedupe_key=dedupe_key)
	return {"awarded": awarded, "user": user, "points": points, "title": title}
