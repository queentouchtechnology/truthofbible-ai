"""Sunday School weekly rewards — student-facing API. Session-cookie auth,
same closed-doctype discipline as `api/reading_plan.py`: every
`TOB Sunday School *` doctype grants no REST access to any role but System
Manager, so this module (plus `api/sunday_school_admin.py` for teacher
actions) is the only door. Ownership/state checks happen here first, then
reads/writes use `ignore_permissions=True`.

Fully separate from the app-wide rewards system (`truth_of_bible.rewards`)
by design — nothing here reads or writes a `TOB Reward *` doctype, and
nothing there reads or writes a `TOB Sunday School *` doctype.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from truth_of_bible.sunday_school import engine


def _require_login():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in."), frappe.PermissionError)
	return frappe.session.user


def _user_brief(users):
	if not users:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", list(users)]}, fields=["name", "full_name", "user_image"])
	return {r.name: r for r in rows}


# Points tables rank what was EARNED. Redemptions / expiries are negative
# ledger rows that only empty the spendable balance, so they're left out
# (otherwise cashing out points would drop a student down this week's
# table, and an all-time table would just show current balances).
_EARNED = "points > 0 and source not in ('Redemption', 'Expired')"


def _rank_rows(week_start, source=None):
	"""week_start None = all time (lifetime points, incl. earlier-system
	rewards added by rewards.legacy.old_sunday_school_points)."""
	conditions = [_EARNED]
	params = []
	if week_start is not None:
		conditions.append("week_start=%s")
		params.append(week_start)
	if source:
		conditions.append("source=%s")
		params.append(source)
	return frappe.db.sql(
		f"""select user, sum(points) as total from `tabTOB Sunday School Points Ledger`
		where {" and ".join(conditions)} group by user order by total desc""",
		params, as_dict=True,
	)


def _group_rank_rows(week_start):
	conditions = [_EARNED, "`group` is not null and `group` != ''"]
	params = []
	if week_start is not None:
		conditions.append("week_start=%s")
		params.append(week_start)
	return frappe.db.sql(
		f"""select `group`, sum(points) as total from `tabTOB Sunday School Points Ledger`
		where {" and ".join(conditions)}
		group by `group` order by total desc""",
		params, as_dict=True,
	)


_KIND_TO_SOURCE = {
	"quiz": "Weekly Quiz",
	"exam": "Faith Leader Exam",
	"verse": "Complete Verse",
	"overall": None,
}


@frappe.whitelist(methods=["GET"])
def get_leaderboard(kind="overall", week_start=None, period="week"):
	"""period "week" (default): the given / current week. "all": lifetime."""
	lifetime = str(period).lower() in ("all", "lifetime", "all_time")
	week = None if lifetime else (engine.week_start_of(week_start) if week_start else engine.week_start_of())

	if kind == "group":
		rows = _group_rank_rows(week)
		names = {r.name: r.group_name for r in frappe.get_all(
			"TOB Sunday School Group", filters={"name": ["in", [r["group"] for r in rows]]}, fields=["name", "group_name"]
		)} if rows else {}
		entries = [
			{"rank": i + 1, "id": r["group"], "name": names.get(r["group"], r["group"]), "image": None, "points": int(r.total)}
			for i, r in enumerate(rows)
		]
	else:
		if kind not in _KIND_TO_SOURCE:
			frappe.throw(_("Unknown leaderboard kind."), frappe.ValidationError)
		rows = _rank_rows(week, _KIND_TO_SOURCE[kind])
		brief = _user_brief([r.user for r in rows])
		entries = [
			{
				"rank": i + 1,
				"id": r.user,
				"name": (brief.get(r.user) or {}).get("full_name") or r.user,
				"image": (brief.get(r.user) or {}).get("user_image"),
				"points": int(r.total),
			}
			for i, r in enumerate(rows)
		]

	my_id = frappe.session.user if frappe.session.user != "Guest" else None
	my_entry = next((e for e in entries if e["id"] == my_id), None)

	return {
		"kind": kind,
		"period": "all" if lifetime else "week",
		"week_start": str(week) if week else None,
		"podium": entries[:3],
		"leaderboard": entries,
		"my_rank": my_entry["rank"] if my_entry else None,
		"my_points": my_entry["points"] if my_entry else 0,
	}


def _weekly_performance(user: str, week, *, current: bool) -> dict:
	"""One student's full challenge performance for one week — quiz, exam,
	verse, group points/rank, any Group Bonus they personally received
	that week, and the Sunday Goal checklist. Shared by get_dashboard
	(always the current week) and get_weekly_performance (any week the
	student has history for — see get_available_weeks), so "This Week" /
	"Last Week" / a picked calendar date all read from exactly one place.
	`current` only changes the quiz-assignment lookup: a live week only
	ever shows the Active assignment (so a since-archived swap doesn't
	confuse "what's this week's challenge"), while a past week shows
	whichever assignment actually existed for it, any status."""
	profile = engine.get_or_create_profile(user)

	quizzes = []
	for quiz_type in ("Weekly Bible Quiz", "Faith Leader Exam"):
		assignment = (
			engine.get_active_quiz_assignment(quiz_type, week)
			if current
			else engine.get_quiz_assignment_for_week(quiz_type, week)
		)
		if not assignment:
			continue
		quiz_info = frappe.db.get_value("LMS Quiz", assignment.lms_quiz, ["title", "total_marks"], as_dict=True)
		if not quiz_info:
			continue
		submission = frappe.db.get_value(
			"LMS Quiz Submission", {"quiz": assignment.lms_quiz, "member": user},
			["score", "score_out_of"], as_dict=True, order_by="creation asc",
		)
		quizzes.append({
			"quiz": assignment.lms_quiz, "quiz_type": quiz_type, "title": quiz_info.title, "status": assignment.status,
			"total_marks": quiz_info.total_marks or (submission.score_out_of if submission else 0),
			"attempted": bool(submission),
			"score": submission.score if submission else None,
		})

	verse_row = frappe.db.get_value(
		"TOB Sunday School Memory Verse", {"week_start": week, "status": "Published"},
		["name", "title", "reference"], as_dict=True,
	)
	verse_info = None
	if verse_row:
		completion = frappe.db.get_value(
			"TOB Sunday School Verse Completion", {"memory_verse": verse_row.name, "user": user},
			["status", "rank"], as_dict=True,
		)
		verse_info = {
			"memory_verse": verse_row.name, "title": verse_row.title, "reference": verse_row.reference,
			"status": completion.status if completion else "Not Started",
			"rank": completion.rank if completion else None,
		}

	group_info = None
	if profile.group:
		group_doc = frappe.get_doc("TOB Sunday School Group", profile.group)
		group_board = get_leaderboard("group", str(week))
		my_group_entry = next((e for e in group_board["leaderboard"] if e["id"] == profile.group), None)
		members = frappe.get_all(
			"TOB Sunday School Profile", filters={"group": profile.group, "status": "Active"}, fields=["user"]
		)
		member_brief = _user_brief([m.user for m in members])
		bonus_points = frappe.db.get_value(
			"TOB Sunday School Points Ledger", {"user": user, "week_start": week, "source": "Group Bonus"}, "points"
		)
		group_info = {
			"group": group_doc.name,
			"group_name": group_doc.group_name,
			"accent_color": group_doc.accent_color,
			"rank": my_group_entry["rank"] if my_group_entry else None,
			"points": my_group_entry["points"] if my_group_entry else 0,
			"is_winner": bool(my_group_entry) and my_group_entry["rank"] == 1,
			"bonus_points_received": int(bonus_points or 0),
			"members": [
				{"name": (member_brief.get(m.user) or {}).get("full_name") or m.user, "image": (member_brief.get(m.user) or {}).get("user_image")}
				for m in members
			],
		}

	attendance = frappe.db.get_value(
		"TOB Sunday School Attendance", {"user": user, "week_start": week},
		["attended_class", "attended_quiz", "completed_memory_verse", "goal_bonus_awarded"], as_dict=True,
	) or {"attended_class": 0, "attended_quiz": 0, "completed_memory_verse": 0, "goal_bonus_awarded": 0}

	points_week = frappe.db.sql(
		"select sum(points) from `tabTOB Sunday School Points Ledger` where user=%s and week_start=%s", (user, week)
	)[0][0] or 0

	return {
		"week_start": str(week),
		"points_this_week": int(points_week),
		"group": group_info,
		"quizzes": quizzes,
		"memory_verse": verse_info,
		"sunday_goal": attendance,
	}


@frappe.whitelist(methods=["GET"])
def get_dashboard():
	user = _require_login()
	profile = engine.get_or_create_profile(user)
	week = engine.week_start_of()

	# Lifetime EARNED (positive rows only) — distinct from the current
	# unredeemed balance (engine.balance()), which drops to 0 on every
	# redemption/expiry. This stat should only ever go up.
	points_all_time = frappe.db.sql(
		"select sum(points) from `tabTOB Sunday School Points Ledger` where user=%s and points > 0", (user,)
	)[0][0] or 0

	overall = get_leaderboard("overall", str(week))
	my_rank = overall["my_rank"]
	weekly = _weekly_performance(user, week, current=True)
	next_up = None
	if my_rank and my_rank > 1:
		ahead = overall["leaderboard"][my_rank - 2]
		next_up = {"points_needed": max(0, ahead["points"] - weekly["points_this_week"] + 1), "target_name": ahead["name"]}

	recent = frappe.get_all(
		"TOB Sunday School Points Ledger", filters=engine.history_filters(user),
		fields=["title", "points", "source", "creation"], order_by="creation desc", limit_page_length=10,
	)

	expiry_info = None
	if profile.points_clock_started_at:
		from frappe.utils import getdate, nowdate

		cfg = engine.settings()
		expiry_days = cfg.points_expiry_days or 14
		started = getdate(profile.points_clock_started_at)
		days_left = expiry_days - (getdate(nowdate()) - started).days
		expiry_info = {"days_left": max(0, days_left), "points": engine.balance(user)}

	return {
		**weekly,
		"points_all_time": int(points_all_time),
		"rank_this_week": my_rank,
		"next_up": next_up,
		"recent_history": recent,
		"expiry": expiry_info,
	}


@frappe.whitelist(methods=["GET"])
def get_weekly_performance(week_start=None):
	"""Same shape as get_dashboard's weekly fields, for any week — the
	This Week / Last Week / calendar-picked view on the Student Dashboard.
	Only ever called for a week get_available_weeks actually returned, but
	tolerates an empty week gracefully either way (every section just
	comes back null/empty rather than erroring)."""
	user = _require_login()
	week = engine.week_start_of(week_start) if week_start else engine.week_start_of()
	current = week == engine.week_start_of()
	return _weekly_performance(user, week, current=current)


@frappe.whitelist(methods=["GET"])
def get_available_weeks():
	"""Every week_start this student has any recorded activity for (points
	earned or attendance marked) — the calendar picker's selectable-dates
	source, so a week they were absent for can't even be picked."""
	user = _require_login()
	ledger_weeks = frappe.get_all("TOB Sunday School Points Ledger", filters={"user": user}, pluck="week_start")
	attendance_weeks = frappe.get_all("TOB Sunday School Attendance", filters={"user": user}, pluck="week_start")
	weeks = sorted({str(w) for w in [*ledger_weeks, *attendance_weeks]}, reverse=True)
	return {"weeks": weeks}


@frappe.whitelist(methods=["GET"])
def get_weekly_winner_group(week_start=None):
	"""This week's (or a given week's) top-scoring group by points, visible
	to every student regardless of which group they're on — a live "who's
	winning right now" banner. Not gated on an admin having run Mark Group
	Winner yet (that's what actually pays the Group Bonus; this is just
	the standings), so it updates the moment points land."""
	week = engine.week_start_of(week_start) if week_start else engine.week_start_of()
	totals = frappe.db.sql(
		"""select `group`, sum(points) as total from `tabTOB Sunday School Points Ledger`
		where week_start=%s and `group` is not null and `group` != ''
		group by `group` order by total desc limit 1""",
		(week,), as_dict=True,
	)
	if not totals:
		return {"week_start": str(week), "group": None}

	top_group = totals[0]["group"]
	group_doc = frappe.get_doc("TOB Sunday School Group", top_group)
	members = frappe.get_all("TOB Sunday School Profile", filters={"group": top_group, "status": "Active"}, fields=["user"])
	brief = _user_brief([m.user for m in members])
	return {
		"week_start": str(week),
		"group": {
			"group": group_doc.name,
			"group_name": group_doc.group_name,
			"accent_color": group_doc.accent_color,
			"points": int(totals[0]["total"]),
			"members": [
				{"name": (brief.get(m.user) or {}).get("full_name") or m.user, "image": (brief.get(m.user) or {}).get("user_image")}
				for m in members
			],
		},
	}


@frappe.whitelist(methods=["POST"])
def redeem_points():
	"""Cashes out the student's whole unredeemed balance into their app
	wallet — see sunday_school/engine.py::redeem_to_wallet for why this is
	the one deliberate bridge between the two otherwise-separate reward
	systems."""
	user = _require_login()
	return engine.redeem_to_wallet(user)


@frappe.whitelist(methods=["POST"])
def mark_memory_verse_complete(memory_verse):
	user = _require_login()
	verse = frappe.get_doc("TOB Sunday School Memory Verse", memory_verse)
	if verse.status != "Published":
		frappe.throw(_("This verse isn't available."), frappe.ValidationError)

	existing = frappe.db.get_value(
		"TOB Sunday School Verse Completion", {"memory_verse": memory_verse, "user": user}, ["name", "status"], as_dict=True
	)
	if existing:
		return {"completion": existing.name, "status": existing.status}

	doc = frappe.get_doc({
		"doctype": "TOB Sunday School Verse Completion",
		"memory_verse": memory_verse, "user": user,
		"status": "Pending", "completed_at": now_datetime(),
	})
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"completion": doc.name, "status": "Pending"}


@frappe.whitelist(methods=["GET"])
def get_memory_verse_courses():
	"""Every course that has at least one Published memory verse, with this
	student's progress — powers the course-picker step ahead of
	get_course_verses(). `course` resolves the linked LMS Course's title
	when set (mirrors analytics/sunday_school_reports.py's own
	coalesce(c.title, mv.course) pattern), falling back to the raw
	Course value for any verse seeded before that link existed."""
	user = _require_login()
	rows = frappe.db.sql(
		"""select mv.course as course_id, coalesce(c.title, mv.course) as course_title, count(*) as total
		from `tabTOB Sunday School Memory Verse` mv
		left join `tabLMS Course` c on c.name = mv.course
		where mv.status = 'Published' and mv.course is not null and mv.course != ''
		group by mv.course, coalesce(c.title, mv.course)
		order by course_title asc""",
		as_dict=True,
	)
	if not rows:
		return {"courses": []}

	studied = frappe.db.sql(
		"""select mv.course as course_id, count(*) as studied
		from `tabTOB Sunday School Verse Completion` vc
		inner join `tabTOB Sunday School Memory Verse` mv on mv.name = vc.memory_verse
		where vc.user = %s and vc.status = 'Verified'
		group by mv.course""",
		(user,), as_dict=True,
	)
	studied_by_course = {r.course_id: r.studied for r in studied}

	return {
		"courses": [
			{
				"course": r.course_id,
				"title": r.course_title,
				"total_verses": r.total,
				"studied_count": studied_by_course.get(r.course_id, 0),
			}
			for r in rows
		]
	}


@frappe.whitelist(methods=["GET"])
def get_course_verses(course):
	"""Every Published verse in one course, in assigned order (oldest
	week_start first, i.e. "Verse 1 of 33"), with this student's own
	completion status/rank per verse — the data behind the course's
	verse-list and verse-slider screens."""
	user = _require_login()
	course_title = frappe.db.get_value("LMS Course", course, "title") or course

	verses = frappe.get_all(
		"TOB Sunday School Memory Verse", filters={"course": course, "status": "Published"},
		fields=["name", "title", "reference", "week_start", "simple_meaning"],
		order_by="week_start asc, creation asc",
	)
	if not verses:
		return {"course": course, "title": course_title, "verses": []}

	completions = frappe.get_all(
		"TOB Sunday School Verse Completion", filters={"user": user, "memory_verse": ["in", [v.name for v in verses]]},
		fields=["memory_verse", "status", "rank"],
	)
	completion_by_verse = {c.memory_verse: c for c in completions}

	out = []
	for i, v in enumerate(verses):
		completion = completion_by_verse.get(v.name)
		out.append({
			"memory_verse": v.name,
			"verse_number": i + 1,
			"title": v.title,
			"reference": v.reference,
			"week_start": str(v.week_start),
			"simple_meaning": v.simple_meaning or "",
			"status": completion.status if completion else "Not Started",
			"rank": completion.rank if completion else None,
		})
	return {"course": course, "title": course_title, "verses": out}


@frappe.whitelist(methods=["GET"])
def get_points_history(date_from=None, date_to=None, source=None, limit=50, offset=0):
	user = _require_login()
	# Admin setting: every row, or only the points still available.
	filters = engine.history_filters(user)
	if source:
		filters["source"] = source
	if date_from and date_to:
		filters["week_start"] = ["between", [date_from, date_to]]

	limit = max(1, min(int(limit), 100))
	offset = max(0, int(offset))

	rows = frappe.get_all(
		"TOB Sunday School Points Ledger", filters=filters,
		fields=["title", "points", "source", "week_start", "creation"],
		order_by="creation desc", limit_page_length=limit, limit_start=offset,
	)
	total = frappe.db.count("TOB Sunday School Points Ledger", filters)
	show_all = engine.show_full_history()
	summary = engine.points_summary(user)
	if not show_all:
		summary = {"available": summary["available"]}
	return {"rows": rows, "total": total, "show_all": show_all, "summary": summary}
