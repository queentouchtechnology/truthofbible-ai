"""One call that tells the app what it should know about the signed-in member
right now — the "global state" the app builds badges, Continue cards and
Discover hints from, instead of every screen working it out on its own.

    pending    something waiting on the member (a support reply, unread
               notifications)
    started    things in progress (reading position, active reading plans,
               courses not finished)
    completed  counters of what they've done
    habit      day streak and this week's active days against the weekly goal
    never_tried  app areas with no activity yet (for gentle Discover hints)
    next       at most 3 suggestions, most useful first, each with the same
               route/id shape push notifications use, so the app can open
               them with its existing deep-link routes

Read-only, cheap queries, only ever about the caller. The app refreshes it
at sign-in, when it comes back to the foreground and after relevant changes
— it is not polled.
"""

import frappe
from frappe.utils import add_days, getdate, strip_html
from frappe.utils.password import get_decrypted_password

from truth_of_bible.rewards import engine as rewards

_MAX_STARTED_COURSES = 3
_MAX_SUGGESTIONS = 3
# Active days a week the app cheers for (Explore's "Weekly goal" card).
_WEEKLY_GOAL_DAYS = 5


def _reading(user):
	row = frappe.db.get_value(
		"TOB User Reading State",
		{"user": user},
		["last_book", "last_book_id", "last_chapter", "last_verse", "last_read_date", "reading_days"],
		as_dict=True,
	)
	if not row or not row.last_book:
		return None
	return {
		"book": row.last_book,
		"book_id": row.last_book_id,
		"chapter": row.last_chapter or 1,
		"verse": row.last_verse or 1,
		"last_read_date": str(row.last_read_date) if row.last_read_date else None,
		"read_today": bool(row.last_read_date) and getdate(row.last_read_date) == getdate(rewards._today()),
		"reading_days": row.reading_days or 0,
	}


def _reading_plans(user):
	rows = frappe.get_all(
		"TOB User Reading Plan",
		filters={"user": user, "status": "Active"},
		fields=["name", "plan", "current_day", "last_activity_at"],
		order_by="last_activity_at desc",
	)
	meta = {
		p.name: p
		for p in frappe.get_all("TOB Reading Plan", filters={"name": ["in", [r.plan for r in rows]]},
			fields=["name", "title", "duration_days"])
	} if rows else {}
	return [
		{"plan": r.plan, "title": (meta.get(r.plan) or {}).get("title") or r.plan, "current_day": r.current_day or 1,
		 "duration_days": (meta.get(r.plan) or {}).get("duration_days") or 0}
		for r in rows
	]


def _courses(user):
	rows = frappe.get_all(
		"LMS Enrollment",
		filters={"member": user, "progress": ["<", 100]},
		fields=["course", "progress"],
		order_by="modified desc",
		limit_page_length=_MAX_STARTED_COURSES,
	)
	meta = {
		c.name: c
		for c in frappe.get_all("LMS Course", filters={"name": ["in", [r.course for r in rows]]},
			fields=["name", "title", "image"])
	} if rows else {}
	return [
		{"course": r.course, "title": (meta.get(r.course) or {}).get("title") or r.course,
		 "image": (meta.get(r.course) or {}).get("image") or None, "progress": round(r.progress or 0)}
		for r in rows
	]


def _habit(user):
	"""Same active days as the Rewards streak (reading, check-in, games, plan
	days) — one query for both numbers."""
	days = rewards._active_days(user)
	today = getdate(rewards._today())
	cursor = today if today in days else add_days(today, -1)
	current = 0
	while cursor in days:
		current += 1
		cursor = getdate(add_days(cursor, -1))
	week_start = add_days(today, -today.weekday())
	return {
		"streak": current,
		"active_today": today in days,
		"week_days": sum(1 for d in days if week_start <= d <= today),
		"weekly_goal": _WEEKLY_GOAL_DAYS,
	}


def _latest_unread(user):
	"""The newest unread notification — what Explore's Live Updates shows."""
	row = frappe.get_all(
		"Notification Log",
		filters={"for_user": user, "read": 0},
		fields=["name", "subject", "creation"],
		order_by="creation desc",
		limit_page_length=1,
	)
	if not row:
		return None
	return {"name": row[0].name, "subject": strip_html(row[0].subject or ""), "at": str(row[0].creation)}


def _has_community_account(user):
	return bool(get_decrypted_password("User", user, "discourse_api_key", raise_exception=False))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_user_context() -> dict:
	user = frappe.session.user
	if user == "Guest":
		return {"signed_in": False}

	replied = frappe.get_all(
		"Issue",
		filters={"raised_by": user, "status": "Replied"},
		fields=["name", "subject", "modified"],
		order_by="modified desc",
	)
	reading = _reading(user)
	plans = _reading_plans(user)
	courses = _courses(user)
	quizzes_taken = frappe.db.count("LMS Quiz Submission", {"member": user})
	enrollments = frappe.db.count("LMS Enrollment", {"member": user})
	today = rewards._today()
	checked_in = bool(frappe.db.count(
		"TOB Reward Ledger", {"user": user, "reason": "daily_checkin", "dedupe_key": ["like", f"daily_checkin:{today}:%"]}
	))

	never_tried = [
		key
		for key, tried in (
			("bible", bool(reading)),
			("reading_plans", bool(plans) or frappe.db.exists("TOB User Reading Plan", {"user": user})),
			("courses", bool(enrollments)),
			("quizzes", bool(quizzes_taken)),
			("ai", frappe.db.exists("TOB AI Usage Log", {"user": user})),
			("games", frappe.db.exists("TOB Game Session", {"user": user})
				or frappe.db.exists("TOB Bible Battle Rating", {"user": user})),
			("community", _has_community_account(user)),
		)
		if not tried
	]

	# Most useful first; each item opens with the app's existing deep links.
	nxt = []
	if replied:
		nxt.append({"kind": "ticket_reply", "title": "Support replied to your ticket",
			"subtitle": replied[0].subject, "route": "/viewTicket", "id": replied[0].name,
			"at": str(replied[0].modified)})
	if reading and not reading["read_today"]:
		nxt.append({"kind": "continue_reading", "title": f"Continue {reading['book']} {reading['chapter']}",
			"subtitle": "Pick up where you left off", "route": "/continueReading",
			"id": f"{reading['book_id']}|{reading['chapter']}|{reading['verse']}"})
	if plans:
		p = plans[0]
		nxt.append({"kind": "reading_plan", "title": p["title"], "subtitle": f"Day {p['current_day']}",
			"route": "/readingPlan", "id": p["plan"]})
	if courses:
		c = courses[0]
		nxt.append({"kind": "continue_course", "title": c["title"], "subtitle": f"{c['progress']}% complete",
			"route": "/viewCourse", "id": c["course"]})
	if not checked_in:
		nxt.append({"kind": "daily_checkin", "title": "Daily check-in", "subtitle": "Earn today's point",
			"route": "/rewards", "id": ""})
	discover_routes = {"reading_plans": "/readingPlans", "courses": "/courseList", "quizzes": "/quizList",
		"community": "/communityBrowse"}
	for key in never_tried:
		if key in discover_routes:
			nxt.append({"kind": "discover", "feature": key, "title": "", "subtitle": "",
				"route": discover_routes[key], "id": ""})
			break  # one Discover hint at a time

	return {
		"signed_in": True,
		"user": user,
		"pending": {
			"ticket_replies": len(replied),
			"open_tickets": frappe.db.count("Issue", {"raised_by": user, "status": ["in", ["Open", "Replied"]]}),
			"unread_notifications": frappe.db.count("Notification Log", {"for_user": user, "read": 0}),
			"latest_notification": _latest_unread(user),
		},
		"started": {"reading": reading, "reading_plans": plans, "courses": courses},
		"completed": {
			"quizzes": quizzes_taken,
			"courses": frappe.db.count("LMS Enrollment", {"member": user, "progress": [">=", 100]}),
			"certificates": frappe.db.count("LMS Certificate", {"member": user}),
			"reading_plans": frappe.db.count("TOB User Reading Plan", {"user": user, "status": "Completed"}),
			"reading_days": reading["reading_days"] if reading else 0,
		},
		"habit": _habit(user),
		"rewards": {"points": rewards.balance(user), "wallet": rewards.wallet_balance(user), "checked_in_today": checked_in},
		"never_tried": never_tried,
		"next": nxt[:_MAX_SUGGESTIONS],
	}
