"""Reading & engagement reports for the admin app's Reports section — Bible
Reading Engagement, Reading Plans, Reading Streaks, and overall User
Engagement. Every function here is admin-only (`require_admin()`) and
strictly read-only: nothing here writes anything, it only aggregates rows
the app's own activity queue (`analytics/activity.py`'s
`TOB User Activity Event`), the reward ledger (`rewards/engine.py`'s
`TOB Reward Ledger`, whose `daily_checkin`/`read_chapter` reasons are the
same streak input `rewards.engine.streak()` uses per-user) and the Reading
Plans feature (`api/reading_plan.py`'s doctypes) already record for other
reasons. Auth matches every other admin report in this app — erpToken, same
as `activity.py`'s `get_activity_summary` — not the session-cookie pattern
`reading_plan.py` uses for its own per-user methods.
"""

import json
from collections import Counter, defaultdict

import frappe
from frappe.utils import add_days, getdate, nowdate

from truth_of_bible.communication.auth import require_admin

_STREAK_REASONS = ("daily_checkin", "read_chapter")


def _names_for(user_ids: list[str]) -> dict:
	if not user_ids:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", user_ids]}, fields=["name", "full_name"])
	return {r.name: r.full_name for r in rows}


# ---------------------------------------------------------------------
# 1. Bible Reading Engagement — highest priority
# ---------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def get_reading_engagement(days=30):
	"""Overview of actual Bible reading activity from `verse_opened` events
	(`{book_id, chapter, version}` payload — see
	`app_analytics_service.dart::logVerseOpened`), not the reward ledger,
	since the ledger caps `read_chapter` at 1/day per user and would
	undercount real reading volume."""
	require_admin()
	days = max(1, min(int(days), 180))
	since = add_days(nowdate(), -(days - 1))
	today = getdate(nowdate())
	week_start = add_days(today, -6)

	rows = frappe.get_all(
		"TOB User Activity Event",
		filters={"event": "verse_opened", "event_time": [">=", since]},
		fields=["user", "event_time", "data"],
	)

	daily = defaultdict(lambda: {"readers": set(), "chapters": 0})
	book_counter = Counter()
	reader_counter = Counter()
	readers_today = set()
	readers_this_week = set()

	for r in rows:
		day = getdate(r.event_time)
		bucket = daily[day.isoformat()]
		bucket["readers"].add(r.user)
		bucket["chapters"] += 1
		reader_counter[r.user] += 1
		if day == today:
			readers_today.add(r.user)
		if day >= week_start:
			readers_this_week.add(r.user)
		try:
			data = json.loads(r.data) if r.data else {}
		except Exception:
			data = {}
		book_id = data.get("book_id")
		if book_id:
			try:
				book_counter[int(book_id)] += 1
			except (TypeError, ValueError):
				pass

	daily_series = [
		{"date": day, "readers": len(v["readers"]), "chapters_read": v["chapters"]}
		for day, v in sorted(daily.items())
	]
	top_books = [{"book_id": b, "count": c} for b, c in book_counter.most_common(10)]

	top_ids = [u for u, _ in reader_counter.most_common(10)]
	names = _names_for(top_ids)
	top_readers = [
		{"user": u, "full_name": names.get(u) or u, "chapters_read": c}
		for u, c in reader_counter.most_common(10)
	]

	return {
		"days": days,
		"total_readers": len(reader_counter),
		"total_chapters_read": sum(reader_counter.values()),
		"readers_today": len(readers_today),
		"readers_this_week": len(readers_this_week),
		"daily_series": daily_series,
		"top_books": top_books,
		"top_readers": top_readers,
	}


# ---------------------------------------------------------------------
# 2. Reading Plans Report
# ---------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def get_reading_plans_report():
	require_admin()

	plans = frappe.get_all(
		"TOB Reading Plan",
		fields=["name", "title", "age_group", "duration_days", "status", "icon", "accent_color"],
		order_by="sort_order asc, title asc",
	)
	if not plans:
		return {"plans": [], "total_enrollments": 0, "total_completions": 0}

	plan_names = [p.name for p in plans]
	enrollments = frappe.get_all(
		"TOB User Reading Plan",
		filters={"plan": ["in", plan_names]},
		fields=["plan", "status", "completed_days"],
	)

	by_plan = defaultdict(list)
	for e in enrollments:
		by_plan[e.plan].append(e)

	rows = []
	total_enrollments = 0
	total_completions = 0
	for p in plans:
		plan_enrollments = by_plan.get(p.name, [])
		started = len(plan_enrollments)
		completed = sum(1 for e in plan_enrollments if e.status == "Completed")
		active = sum(1 for e in plan_enrollments if e.status == "Active")
		abandoned = sum(1 for e in plan_enrollments if e.status == "Abandoned")

		progress_values = []
		for e in plan_enrollments:
			if e.status == "Completed":
				progress_values.append(100)
				continue
			try:
				completed_days = json.loads(e.completed_days or "[]")
			except Exception:
				completed_days = []
			if p.duration_days:
				progress_values.append(min(100, round(len(completed_days) / p.duration_days * 100)))

		avg_progress = round(sum(progress_values) / len(progress_values)) if progress_values else 0
		completion_rate = round(completed / started * 100) if started else 0

		total_enrollments += started
		total_completions += completed

		rows.append(
			{
				"plan": p.name,
				"title": p.title,
				"age_group": p.age_group,
				"status": p.status,
				"icon": p.icon,
				"accent_color": p.accent_color,
				"started": started,
				"active": active,
				"completed": completed,
				"abandoned": abandoned,
				"completion_rate": completion_rate,
				"avg_progress_percent": avg_progress,
			}
		)

	rows.sort(key=lambda r: r["started"], reverse=True)
	return {"plans": rows, "total_enrollments": total_enrollments, "total_completions": total_completions}


# ---------------------------------------------------------------------
# 3. Reading Streak Report
# ---------------------------------------------------------------------


def _best_streak_in_window(days: set) -> int:
	if not days:
		return 0
	ordered = sorted(days)
	best = run = 1
	for i in range(1, len(ordered)):
		if ordered[i] == add_days(ordered[i - 1], 1):
			run += 1
			best = max(best, run)
		else:
			run = 1
	return best


@frappe.whitelist(methods=["GET"])
def get_streak_report(limit=20):
	"""Same streak definition as `rewards.engine.streak()` (consecutive
	calendar days with a `daily_checkin` or `read_chapter` reward-ledger
	entry, today counting if already earned) — computed here in one
	aggregate query across every user instead of one `streak()` call per
	user, which would be an N-query report page."""
	require_admin()
	limit = max(1, min(int(limit), 100))

	since = add_days(nowdate(), -120)
	rows = frappe.db.sql(
		"""
		select user, date(creation) as day
		from `tabTOB Reward Ledger`
		where reason in %s and creation >= %s
		group by user, date(creation)
		""",
		(_STREAK_REASONS, since),
		as_dict=True,
	)

	days_by_user = defaultdict(set)
	for r in rows:
		days_by_user[r.user].add(getdate(r.day))

	today = getdate(nowdate())

	def current_streak(days: set) -> int:
		cursor = today if today in days else add_days(today, -1)
		count = 0
		while cursor in days:
			count += 1
			cursor = add_days(cursor, -1)
		return count

	streaks = [
		{"user": user, "current_streak": current_streak(days), "best_streak_120d": _best_streak_in_window(days)}
		for user, days in days_by_user.items()
	]
	streaks.sort(key=lambda s: s["current_streak"], reverse=True)

	active = [s for s in streaks if s["current_streak"] > 0]
	distribution = {"1-2": 0, "3-6": 0, "7-13": 0, "14-29": 0, "30+": 0}
	for s in active:
		n = s["current_streak"]
		bucket = "1-2" if n <= 2 else "3-6" if n <= 6 else "7-13" if n <= 13 else "14-29" if n <= 29 else "30+"
		distribution[bucket] += 1

	top = streaks[:limit]
	names = _names_for([s["user"] for s in top])
	for s in top:
		s["full_name"] = names.get(s["user"]) or s["user"]

	avg_streak = round(sum(s["current_streak"] for s in active) / len(active), 1) if active else 0

	return {
		"users_with_active_streak": len(active),
		"avg_streak": avg_streak,
		"distribution": distribution,
		"leaderboard": top,
	}


# ---------------------------------------------------------------------
# 4. User Engagement Report
# ---------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def get_user_engagement_report(days=30):
	require_admin()
	days = max(1, min(int(days), 180))
	since = add_days(nowdate(), -(days - 1))
	today = getdate(nowdate())
	week_start = add_days(today, -6)

	rows = frappe.get_all(
		"TOB User Activity Event",
		filters={"event_time": [">=", since]},
		fields=["user", "event", "event_time", "data"],
	)

	dau = {r.user for r in rows if getdate(r.event_time) == today}
	wau = {r.user for r in rows if getdate(r.event_time) >= week_start}
	mau = {r.user for r in rows}

	daily = defaultdict(set)
	for r in rows:
		daily[getdate(r.event_time).isoformat()].add(r.user)
	daily_active_series = [{"date": d, "active_users": len(u)} for d, u in sorted(daily.items())]

	event_counter = Counter(r.event for r in rows)
	event_breakdown = [{"event": e, "count": c} for e, c in event_counter.most_common(15)]

	session_durations = []
	for r in rows:
		if r.event != "app_session_ended":
			continue
		try:
			data = json.loads(r.data) if r.data else {}
		except Exception:
			data = {}
		secs = data.get("duration_seconds")
		if isinstance(secs, (int, float)) and secs > 0:
			session_durations.append(secs)
	avg_session_seconds = round(sum(session_durations) / len(session_durations)) if session_durations else 0

	# "New" = this active user's very first-ever recorded event also falls
	# inside the report window; everyone else active in the window is
	# "returning".
	active_users = list(mau)
	new_users = 0
	if active_users:
		first_seen_rows = frappe.db.sql(
			"""
			select user, min(event_time) as first_seen
			from `tabTOB User Activity Event`
			where user in %s
			group by user
			""",
			(tuple(active_users),),
			as_dict=True,
		)
		since_date = getdate(since)
		for r in first_seen_rows:
			if getdate(r.first_seen) >= since_date:
				new_users += 1
	returning_users = len(active_users) - new_users

	user_counter = Counter(r.user for r in rows)
	top_ids = [u for u, _ in user_counter.most_common(10)]
	names = _names_for(top_ids)
	top_engaged_users = [
		{"user": u, "full_name": names.get(u) or u, "event_count": c}
		for u, c in user_counter.most_common(10)
	]

	return {
		"days": days,
		"dau": len(dau),
		"wau": len(wau),
		"mau": len(mau),
		"daily_active_series": daily_active_series,
		"avg_session_seconds": avg_session_seconds,
		"new_users": new_users,
		"returning_users": returning_users,
		"event_breakdown": event_breakdown,
		"top_engaged_users": top_engaged_users,
	}
