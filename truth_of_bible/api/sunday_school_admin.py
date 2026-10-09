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
def get_pending_verse_completions(memory_verse=None, course=None):
	"""The verification queue's own row shape — joins in what verse was
	recited (title/reference), which course it belongs to, and the
	student's avatar, so the admin isn't approving a bare name + timestamp
	blind. `course` filters client-side-derived tabs the same way
	`memory_verse` already did."""
	require_admin()
	conditions = ["vc.status = 'Pending'"]
	values = {}
	if memory_verse:
		conditions.append("vc.memory_verse = %(memory_verse)s")
		values["memory_verse"] = memory_verse
	if course:
		conditions.append("mv.course = %(course)s")
		values["course"] = course
	where = " and ".join(conditions)
	rows = frappe.db.sql(
		f"""select vc.name, vc.memory_verse, vc.user, vc.completed_at,
			mv.title as verse_title, mv.reference as verse_reference,
			mv.course as course_id, coalesce(c.title, mv.course) as course_title,
			u.full_name, u.user_image
		from `tabTOB Sunday School Verse Completion` vc
		inner join `tabTOB Sunday School Memory Verse` mv on mv.name = vc.memory_verse
		left join `tabLMS Course` c on c.name = mv.course
		left join `tabUser` u on u.name = vc.user
		where {where}
		order by vc.completed_at asc""",
		values, as_dict=True,
	)
	return {"rows": rows}


@frappe.whitelist(methods=["POST"])
def verify_verse_completion(completion, verified, rank=None):
	"""`rank` is ignored (older app versions still send it): verifying no
	longer awards points — see engine.verify_verse_completion."""
	require_admin()
	verified = str(verified).lower() in ("1", "true", "yes")
	return engine.verify_verse_completion(completion, verified)


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


_DEFAULT_REASONS = [
	engine.COMPLETE_VERSE_REASON,
	"Bible reading",
	"Prayer participation",
	"Helping in class",
	"Bringing a friend",
	"Good behaviour",
	"Late to class",
]
_AUTO_TITLES = ("Manual point adjustment", "Manual point deduction")


@frappe.whitelist(methods=["GET"])
def list_point_reasons():
	"""Reasons for the Point Entry dropdown: every reason admins have used
	before (most used first), then the starter list. A "new" reason needs
	no saving step — it joins this list the first time points are given
	with it."""
	require_admin()
	used = frappe.db.sql(
		"""select title, count(*) as uses from `tabTOB Sunday School Points Ledger`
		where source = 'Manual Adjustment' and ifnull(title, '') != '' and title not in %s
		group by title order by uses desc, title asc limit 100""",
		(_AUTO_TITLES,), as_dict=True,
	)
	# Complete Verse always first (it feeds the Complete Verse leaderboard).
	reasons = [engine.COMPLETE_VERSE_REASON] + [r.title for r in used if r.title != engine.COMPLETE_VERSE_REASON]
	seen = {r.lower() for r in reasons}
	reasons += [r for r in _DEFAULT_REASONS if r.lower() not in seen]
	return {"reasons": reasons}


def split_points(total: int, users: list) -> list:
	"""Splits [total] across [users] as evenly as whole points allow: each
	gets total ÷ n, and the remainder goes one extra point each to the first
	users (sorted, so the split is the same every time). Members whose
	share is 0 are left out. Works for deductions (negative totals) too."""
	users = sorted(users)
	if not users:
		return []
	sign = -1 if total < 0 else 1
	base, extra = divmod(abs(total), len(users))
	shares = [(u, sign * (base + (1 if i < extra else 0))) for i, u in enumerate(users)]
	return [(u, p) for u, p in shares if p]


@frappe.whitelist(methods=["POST"])
def add_group_points(group, points, title=None, week_start=None):
	"""Point Entry for a whole group: [points] is the group's TOTAL, split
	across its active members (see split_points). Each member gets their
	own Manual Adjustment row, tagged with the group."""
	require_admin()
	points = int(points)
	if points == 0:
		frappe.throw(_("Points must not be zero."), frappe.ValidationError)
	if not frappe.db.exists("TOB Sunday School Group", group):
		frappe.throw(_("Group not found."), frappe.DoesNotExistError)
	members = frappe.get_all(
		"TOB Sunday School Profile", filters={"group": group, "status": "Active"}, pluck="user"
	)
	if not members:
		frappe.throw(_("This group has no members yet."), frappe.ValidationError)

	week = getdate(week_start) if week_start else engine.week_start_of()
	title = title or ("Manual point adjustment" if points > 0 else "Manual point deduction")
	batch = frappe.generate_hash(length=12)
	awarded = []
	for user, share in split_points(points, members):
		if engine.award(user, "Manual Adjustment", title, share, week_start=week, group=group,
				dedupe_key=f"manualgroup:{batch}:{user}"):
			awarded.append({"user": user, "points": share})
	return {"group": group, "points": points, "title": title, "members": awarded}


@frappe.whitelist(methods=["GET"])
def list_role_students(search=None):
	"""Every user actually holding the "Sunday School Student" role (see
	install.py::ensure_sunday_school_role) — the one picker source for
	both the Attendance roster and Group Members screens, so an admin can
	only ever add a real activated student, never an arbitrary typed
	email. Left-joins TOB Sunday School Profile (created lazily on first
	dashboard load) so a role-holder who's never opened the app yet still
	shows up, just with no group/location/referral data yet — mirrors
	notifications/triggers.py::_sunday_school_students()'s own reasoning
	for querying the role directly rather than the Profile doctype.

	Also left-joins a lifetime Points Ledger total so admin list/picker
	screens can show a student's faith points alongside their name,
	instead of a bare name-and-email row."""
	require_admin()
	conditions = "hr.role = 'Sunday School Student' and hr.parenttype = 'User' and u.enabled = 1"
	params = {}
	if search:
		conditions += " and (u.name like %(search)s or u.full_name like %(search)s)"
		params["search"] = f"%{search}%"
	return frappe.db.sql(
		f"""select u.name as user, u.full_name, u.user_image,
			p.name as profile, p.group as `group`, p.location, p.referred_by, p.status,
			coalesce(pl.total_points, 0) as total_points
		from `tabHas Role` hr
		inner join `tabUser` u on u.name = hr.parent
		left join `tabTOB Sunday School Profile` p on p.user = u.name
		left join (
			select user, sum(points) as total_points
			from `tabTOB Sunday School Points Ledger`
			group by user
		) pl on pl.user = u.name
		where {conditions}
		order by u.full_name asc
		limit 300""",
		params, as_dict=True,
	)
