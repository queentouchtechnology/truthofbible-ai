"""Admin reports for the Sunday School weekly rewards system —
`require_admin()`-gated, read-only, mirroring `analytics/reading_reports.py`'s
shape. Leaderboard ranking itself is delegated to
`api.sunday_school.get_leaderboard` rather than re-implemented here, so
there's exactly one ranking query in the codebase.
"""

import frappe

from truth_of_bible.communication.auth import require_admin
from truth_of_bible.sunday_school import engine
from truth_of_bible.api import sunday_school as student_api

# Assigned by all-time points earned (lifetime, positive rows only — see
# api/sunday_school.py's points_all_time query) — a pure, deterministic
# tier table rather than a database-driven one, since the user just asked
# for names to be "assigned", not for the thresholds to be admin-tunable.
_TITLE_TIERS = [
	(0, "New Believer"),
	(50, "Faithful Servant"),
	(150, "Rising Star"),
	(300, "Verse Master"),
	(500, "Faith Leader"),
	(1000, "Kingdom Champion"),
]


def _title_for_points(points: int) -> str:
	title = _TITLE_TIERS[0][1]
	for threshold, name in _TITLE_TIERS:
		if points >= threshold:
			title = name
	return title


def _user_brief(users) -> dict:
	if not users:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", list(set(users))]}, fields=["name", "full_name", "user_image"])
	return {r.name: r for r in rows}


@frappe.whitelist(methods=["GET"])
def get_overview_stats():
	require_admin()
	week = engine.week_start_of()
	return {
		"week_start": str(week),
		"total_students": frappe.db.count("TOB Sunday School Profile", {"status": "Active"}),
		"total_groups": frappe.db.count("TOB Sunday School Group", {"status": "Active"}),
		"points_awarded_this_week": int(
			frappe.db.sql(
				"select sum(points) from `tabTOB Sunday School Points Ledger` where week_start=%s", (week,)
			)[0][0] or 0
		),
		"points_awarded_all_time": int(
			frappe.db.sql("select sum(points) from `tabTOB Sunday School Points Ledger`")[0][0] or 0
		),
		"open_quizzes": frappe.db.count("TOB Sunday School Weekly Quiz", {"status": "Published"}),
		"pending_verse_verifications": frappe.db.count("TOB Sunday School Verse Completion", {"status": "Pending"}),
	}


@frappe.whitelist(methods=["GET"])
def get_weekly_leaderboard_report(kind="overall", week_start=None):
	require_admin()
	return student_api.get_leaderboard(kind=kind, week_start=week_start)


@frappe.whitelist(methods=["GET"])
def get_group_standings():
	require_admin()
	week = engine.week_start_of()
	this_week = student_api.get_leaderboard("group", str(week))["leaderboard"]

	all_time_rows = frappe.db.sql(
		"""select `group`, sum(points) as total from `tabTOB Sunday School Points Ledger`
		where `group` is not null and `group` != '' group by `group` order by total desc""",
		as_dict=True,
	)
	names = {}
	if all_time_rows:
		names = {
			g.name: g.group_name
			for g in frappe.get_all(
				"TOB Sunday School Group", filters={"name": ["in", [r["group"] for r in all_time_rows]]},
				fields=["name", "group_name"],
			)
		}
	all_time = [
		{"rank": i + 1, "group": r["group"], "group_name": names.get(r["group"], r["group"]), "points": int(r.total)}
		for i, r in enumerate(all_time_rows)
	]
	return {"week_start": str(week), "this_week": this_week, "all_time": all_time}


@frappe.whitelist(methods=["GET"])
def get_group_scoreboard(week_start=None):
	"""Cricket-scoreboard-style view: every active group this week, ranked, each
	with its member roster (avatar + this-week points) so the admin can see who's
	carrying the team, not just the team total."""
	require_admin()
	week = engine.week_start_of(week_start) if week_start else engine.week_start_of()
	groups = frappe.get_all(
		"TOB Sunday School Group", filters={"status": "Active"},
		fields=["name", "group_name", "location", "accent_color"],
	)
	if not groups:
		return {"week_start": str(week), "groups": []}

	group_names = [g.name for g in groups]
	members = frappe.get_all(
		"TOB Sunday School Profile", filters={"group": ["in", group_names], "status": "Active"},
		fields=["user", "group"],
	)
	members_by_group = {}
	for m in members:
		members_by_group.setdefault(m.group, []).append(m.user)

	week_points_rows = frappe.get_all(
		"TOB Sunday School Points Ledger", filters={"week_start": week, "user": ["in", [m.user for m in members]] or [""]},
		fields=["user", "points"],
	)
	week_points_by_user = {}
	for r in week_points_rows:
		week_points_by_user[r.user] = week_points_by_user.get(r.user, 0) + r.points

	brief = _user_brief([m.user for m in members])

	out = []
	for g in groups:
		roster = []
		total = 0
		for user in members_by_group.get(g.name, []):
			pts = week_points_by_user.get(user, 0)
			total += pts
			u = brief.get(user)
			roster.append({
				"user": user,
				"full_name": u.full_name if u else user,
				"user_image": u.user_image if u else None,
				"points_this_week": int(pts),
			})
		roster.sort(key=lambda r: r["points_this_week"], reverse=True)
		out.append({
			"group": g.name,
			"group_name": g.group_name,
			"location": g.location,
			"accent_color": g.accent_color,
			"points_this_week": int(total),
			"members": roster,
		})
	out.sort(key=lambda g: g["points_this_week"], reverse=True)
	for i, g in enumerate(out):
		g["rank"] = i + 1
	return {"week_start": str(week), "groups": out}


@frappe.whitelist(methods=["GET"])
def get_attendance_report(week_start=None):
	require_admin()
	week = engine.week_start_of(week_start) if week_start else engine.week_start_of()
	rows = frappe.get_all(
		"TOB Sunday School Attendance", filters={"week_start": week},
		fields=["name", "user", "attended_class", "attended_quiz", "completed_memory_verse", "goal_bonus_awarded"],
	)
	present = [r for r in rows if r.attended_class or r.attended_quiz]
	brief = _user_brief([r.user for r in rows])
	for r in rows:
		u = brief.get(r.user)
		r["full_name"] = u.full_name if u else r.user
		r["user_image"] = u.user_image if u else None
	return {
		"week_start": str(week),
		"rows": rows,
		"present_count": len(present),
		"total_count": len(rows),
	}


@frappe.whitelist(methods=["GET"])
def get_verse_mastery_report():
	"""How many memory verses each student knows (Verified completions), broken
	down by course, plus a per-course totals summary."""
	require_admin()
	rows = frappe.db.sql(
		"""select vc.user as user, coalesce(c.title, mv.course) as course
		from `tabTOB Sunday School Verse Completion` vc
		inner join `tabTOB Sunday School Memory Verse` mv on mv.name = vc.memory_verse
		left join `tabLMS Course` c on c.name = mv.course
		where vc.status = 'Verified'""",
		as_dict=True,
	)
	if not rows:
		return {"students": [], "by_course": []}

	brief = _user_brief([r.user for r in rows])
	per_student = {}
	per_course = {}
	for r in rows:
		course = r.course or "Uncategorized"
		s = per_student.setdefault(r.user, {"total": 0, "courses": {}})
		s["total"] += 1
		s["courses"][course] = s["courses"].get(course, 0) + 1
		per_course[course] = per_course.get(course, 0) + 1

	students = []
	for user, s in per_student.items():
		u = brief.get(user)
		students.append({
			"user": user,
			"full_name": u.full_name if u else user,
			"user_image": u.user_image if u else None,
			"verses_known": s["total"],
			"by_course": [{"course": c, "count": n} for c, n in sorted(s["courses"].items(), key=lambda x: -x[1])],
		})
	students.sort(key=lambda s: s["verses_known"], reverse=True)
	by_course = [{"course": c, "students_count": n} for c, n in sorted(per_course.items(), key=lambda x: -x[1])]
	return {"students": students, "by_course": by_course}


@frappe.whitelist(methods=["GET"])
def get_quiz_performance_report():
	"""Per-quiz attempt counts and score stats, for both Weekly Bible Quiz and
	Faith Leader Exam types."""
	require_admin()
	quizzes = frappe.get_all(
		"TOB Sunday School Weekly Quiz",
		fields=["name", "title", "quiz_type", "week_start", "status", "total_marks"],
		order_by="week_start desc",
		limit_page_length=100,
	)
	if not quizzes:
		return {"quizzes": []}

	attempts = frappe.get_all(
		"TOB Sunday School Quiz Attempt", filters={"quiz": ["in", [q.name for q in quizzes]]},
		fields=["quiz", "user", "score", "total_marks", "rank"],
	)
	by_quiz = {}
	for a in attempts:
		by_quiz.setdefault(a.quiz, []).append(a)

	brief = _user_brief([a.user for a in attempts])
	out = []
	for q in quizzes:
		rows = by_quiz.get(q.name, [])
		scores = [a.score for a in rows]
		top = sorted(rows, key=lambda a: a.score, reverse=True)[:3]
		out.append({
			"quiz": q.name,
			"title": q.title,
			"quiz_type": q.quiz_type,
			"week_start": str(q.week_start),
			"status": q.status,
			"total_marks": q.total_marks,
			"attempts_count": len(rows),
			"average_score": round(sum(scores) / len(scores), 1) if scores else 0,
			"highest_score": max(scores) if scores else 0,
			"top_scorers": [
				{
					"user": a.user,
					"full_name": brief.get(a.user).full_name if brief.get(a.user) else a.user,
					"user_image": brief.get(a.user).user_image if brief.get(a.user) else None,
					"score": a.score,
					"rank": a.rank,
				}
				for a in top
			],
		})
	return {"quizzes": out}


@frappe.whitelist(methods=["GET"])
def get_referral_report(location=None):
	"""Who referred how many new students — location-scoped when `location` is
	passed, otherwise global across all Sunday School sites."""
	require_admin()
	filters = {"referred_by": ["is", "set"]}
	if location:
		filters["location"] = location
	rows = frappe.get_all("TOB Sunday School Profile", filters=filters, fields=["user", "referred_by", "location"])
	if not rows:
		return {"location": location, "referrers": [], "total_referrals": 0}

	brief = _user_brief([r.referred_by for r in rows] + [r.user for r in rows])
	per_referrer = {}
	for r in rows:
		entry = per_referrer.setdefault(r.referred_by, {"count": 0, "referred": []})
		entry["count"] += 1
		u = brief.get(r.user)
		entry["referred"].append({"user": r.user, "full_name": u.full_name if u else r.user, "location": r.location})

	referrers = []
	for referrer, entry in per_referrer.items():
		u = brief.get(referrer)
		referrers.append({
			"user": referrer,
			"full_name": u.full_name if u else referrer,
			"user_image": u.user_image if u else None,
			"referral_count": entry["count"],
			"referred": entry["referred"],
		})
	referrers.sort(key=lambda r: r["referral_count"], reverse=True)
	return {"location": location, "referrers": referrers, "total_referrals": len(rows)}


@frappe.whitelist(methods=["GET"])
def get_daily_habits_report(date=None):
	"""Which Sunday School students read the Bible / prayed on a given day —
	reuses the existing app-wide TOB User Activity Event log (verse_opened /
	prayer_topic_explored) rather than tracking these separately."""
	require_admin()
	day = frappe.utils.getdate(date) if date else frappe.utils.today()
	students = frappe.get_all("TOB Sunday School Profile", filters={"status": "Active"}, fields=["user"])
	student_users = [s.user for s in students]
	if not student_users:
		return {"date": str(day), "students": []}

	events = frappe.db.sql(
		"""select `user`, `event` from `tabTOB User Activity Event`
		where `user` in %(users)s and `event` in ('verse_opened', 'prayer_topic_explored')
		and date(event_time) = %(day)s""",
		{"users": student_users, "day": day},
		as_dict=True,
	)
	read_bible = set()
	prayed = set()
	for e in events:
		if e.event == "verse_opened":
			read_bible.add(e.user)
		elif e.event == "prayer_topic_explored":
			prayed.add(e.user)

	brief = _user_brief(student_users)
	out = []
	for user in student_users:
		u = brief.get(user)
		out.append({
			"user": user,
			"full_name": u.full_name if u else user,
			"user_image": u.user_image if u else None,
			"read_bible": user in read_bible,
			"prayed": user in prayed,
		})
	out.sort(key=lambda s: (not s["read_bible"], not s["prayed"], s["full_name"]))
	return {
		"date": str(day),
		"students": out,
		"read_bible_count": len(read_bible),
		"prayed_count": len(prayed),
		"total_students": len(student_users),
	}


@frappe.whitelist(methods=["GET"])
def get_student_titles():
	"""Assigns each active student a spiritual-growth title (e.g. "Faith
	Leader") based on their all-time points earned — see _TITLE_TIERS."""
	require_admin()
	students = frappe.get_all("TOB Sunday School Profile", filters={"status": "Active"}, fields=["user"])
	if not students:
		return {"students": []}
	student_users = [s.user for s in students]

	points_rows = frappe.db.sql(
		"""select `user`, sum(points) as total from `tabTOB Sunday School Points Ledger`
		where `user` in %(users)s and points > 0 group by `user`""",
		{"users": student_users}, as_dict=True,
	)
	points_by_user = {r.user: int(r.total or 0) for r in points_rows}
	brief = _user_brief(student_users)

	out = []
	for user in student_users:
		pts = points_by_user.get(user, 0)
		u = brief.get(user)
		out.append({
			"user": user,
			"full_name": u.full_name if u else user,
			"user_image": u.user_image if u else None,
			"points_all_time": pts,
			"title": _title_for_points(pts),
		})
	out.sort(key=lambda s: s["points_all_time"], reverse=True)
	return {"students": out, "tiers": [{"threshold": t, "title": n} for t, n in _TITLE_TIERS]}


@frappe.whitelist(methods=["GET"])
def get_student_history(user):
	require_admin()
	profile = frappe.db.get_value(
		"TOB Sunday School Profile", user, ["group", "status"], as_dict=True
	)
	ledger = frappe.get_all(
		"TOB Sunday School Points Ledger", filters={"user": user},
		fields=["title", "points", "source", "week_start", "creation"], order_by="creation desc", limit_page_length=100,
	)
	quiz_attempts = frappe.get_all(
		"TOB Sunday School Quiz Attempt", filters={"user": user},
		fields=["quiz", "score", "total_marks", "rank", "submitted_at"], order_by="submitted_at desc",
	)
	verse_completions = frappe.get_all(
		"TOB Sunday School Verse Completion", filters={"user": user},
		fields=["memory_verse", "status", "rank", "completed_at"], order_by="completed_at desc",
	)
	return {
		"user": user,
		"profile": profile,
		"points_history": ledger,
		"quiz_attempts": quiz_attempts,
		"verse_completions": verse_completions,
	}
