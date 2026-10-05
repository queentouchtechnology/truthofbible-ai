"""Bible Reading Plans — browse, start and follow multi-day plans, with
habits (streaks, calendar, schedule + catch-up, reminders), rewards (XP,
points, badges), reflection (a question + a private journal note per day)
and reading together (friends by invite code, or a Sunday School group).

Every doctype here (`TOB Reading Plan`, `TOB Reading Plan Day`,
`TOB User Reading Plan`, `TOB Reading Plan Note`, `TOB Reading Plan Group`)
is closed to raw `/api/resource/...` REST for every role except System
Manager — this file is the only door. Ownership/state checks happen here
first, then the actual read/write uses `ignore_permissions=True`.
Session-cookie auth (login required).

Enrollment lifecycle (one row per user + plan "run"):
- Start: reuses the user's Abandoned row for that plan, so leaving a plan
  and coming back keeps the ticked days. A finished plan stays Completed as
  history; `restart_plan` begins a fresh run.
- The current day is always the FIRST unticked day — ticking ahead never
  skips the days before it, and unticking moves it back.
- Unticking a day on a finished plan reopens it (Active again).
- Progress is always counted against the plan's actual day rows, never the
  free-typed `duration_days`, so every screen shows the same number.
- Schedule: Day 1 is `schedule_start` (defaults to the start date); a day
  is "behind" once its scheduled date has passed unread. `catch_up` moves
  the schedule so today = the current day — no guilt, just a fresh start.
"""

import json
import random

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, get_time, getdate, now_datetime, nowdate

from truth_of_bible.reading_plans.catalog import reflection_for

# Best row to show for a plan when a user has several runs of it.
_STATUS_RANK = {"Active": 0, "Completed": 1, "Abandoned": 2}

DAY_XP = 10
FINISH_XP = 50
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _user() -> str:
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in."), frappe.PermissionError)
	return frappe.session.user


def _plan_dict(p) -> dict:
	return {
		"plan": p.name,
		"title": p.title,
		"age_group": p.age_group,
		"description": p.description or "",
		"duration_days": p.duration_days or 0,
		"difficulty": p.difficulty,
		"icon": p.icon,
		"accent_color": p.accent_color,
		"category": p.get("category") or "Starter",
	}


def _segments(d) -> list:
	try:
		segs = json.loads(d.get("segments") or "null")
		if isinstance(segs, list) and segs:
			return [[int(b), int(s), int(e)] for b, s, e in segs]
	except (ValueError, TypeError):
		pass
	return [[int(d.book_id or 1), int(d.chapter_start or 1), int(d.chapter_end or d.chapter_start or 1)]]


def _day_dict(d) -> dict:
	segs = _segments(d)
	return {
		"day_number": d.day_number,
		"title": d.title or "",
		"reference_label": d.reference_label,
		"book_id": d.book_id,
		"chapter_start": d.chapter_start,
		"chapter_end": d.chapter_end or d.chapter_start,
		"segments": segs,
		"chapter_count": sum(e - s + 1 for _, s, e in segs),
		"note": d.note or "",
		"reflection": d.get("reflection") or reflection_for(d.day_number),
	}


_DAY_FIELDS = ["day_number", "title", "reference_label", "book_id", "chapter_start", "chapter_end", "note", "segments", "reflection"]


def _completed_days(enrollment) -> list:
	try:
		days = json.loads(enrollment.completed_days or "[]")
		return sorted({int(d) for d in days})
	except Exception:
		return []


def _log(enrollment) -> dict:
	try:
		data = json.loads(enrollment.get("completion_log") or "{}")
		return data if isinstance(data, dict) else {}
	except ValueError:
		return {}


def _day_numbers(plan: str) -> list[int]:
	return frappe.get_all(
		"TOB Reading Plan Day", filters={"plan": plan}, pluck="day_number", order_by="day_number asc",
		ignore_permissions=True,
	)


def _day_counts(plans: list[str]) -> dict:
	if not plans:
		return {}
	rows = frappe.db.sql(
		"select plan, count(*) from `tabTOB Reading Plan Day` where plan in %s group by plan", (tuple(plans),)
	)
	return {r[0]: int(r[1]) for r in rows}


def next_day(completed, day_numbers: list[int]) -> int:
	"""The first day not yet ticked; the last day when all are done."""
	done = set(completed)
	for n in day_numbers:
		if n not in done:
			return n
	return day_numbers[-1] if day_numbers else 1


def _percent(completed: list, day_count: int) -> int:
	return min(100, round(len(completed) / day_count * 100)) if day_count else 0


def _schedule(e, day_numbers: list[int]) -> dict:
	"""Where the user "should" be, and how many scheduled days are unread."""
	start = getdate(e.get("schedule_start") or e.started_at or nowdate())
	today = getdate(nowdate())
	elapsed = max(0, date_diff(today, start))
	completed = set(_completed_days(e))
	due = [n for i, n in enumerate(day_numbers) if i <= elapsed]
	behind = 0 if e.status != "Active" else sum(1 for n in due if n not in completed)
	finish = add_days(start, max(0, len(day_numbers) - 1))
	return {
		"schedule_start": str(start),
		"scheduled_day": due[-1] if due else (day_numbers[0] if day_numbers else 1),
		"behind": behind,
		"finish_date": str(finish),
	}


def _enrollment_dict(e, day_numbers) -> dict:
	if isinstance(day_numbers, int):  # older callers passed a count
		day_numbers = list(range(1, day_numbers + 1))
	completed = _completed_days(e)
	reminder = e.get("reminder_time")
	return {
		"plan": e.plan,
		"status": e.status,
		"current_day": e.current_day or 1,
		"completed_days": completed,
		"completion_log": _log(e),
		"progress_percent": _percent(completed, len(day_numbers)),
		"started_at": e.started_at,
		"completed_at": e.completed_at,
		"reminder_time": str(get_time(reminder))[:5] if reminder else None,
		"group": e.get("reading_group"),
		**_schedule(e, day_numbers),
	}


def _lock_user(user: str) -> None:
	"""Serialises one user's enrollment writes — a double tap on Start can
	never create two Active runs of the same plan."""
	frappe.db.sql("select name from `tabUser` where name=%s for update", user)


def _latest(user: str, plan: str, status: str, for_update: bool = False):
	name = frappe.db.get_value(
		"TOB User Reading Plan", {"user": user, "plan": plan, "status": status}, "name", order_by="modified desc"
	)
	return frappe.get_doc("TOB User Reading Plan", name, for_update=for_update) if name else None


def _get_active_enrollment(user: str, plan: str, for_update: bool = False):
	return _latest(user, plan, "Active", for_update)


def _require_active(user: str, plan: str):
	e = _get_active_enrollment(user, plan, for_update=True)
	if not e:
		frappe.throw(_("Start this plan first."), frappe.ValidationError)
	return e


def _best_rows(user: str, plans: list[str] | None = None) -> dict:
	"""plan -> the row to show: Active, else the latest Completed."""
	filters = {"user": user, "status": ["in", ["Active", "Completed"]]}
	if plans is not None:
		filters["plan"] = ["in", plans or [""]]
	rows = frappe.get_all(
		"TOB User Reading Plan",
		filters=filters,
		fields=["name", "plan", "status", "current_day", "completed_days", "started_at", "completed_at", "modified", "reading_group"],
		order_by="modified desc",
		ignore_permissions=True,
	)
	best = {}
	for r in rows:
		cur = best.get(r.plan)
		if cur is None or _STATUS_RANK[r.status] < _STATUS_RANK[cur.status]:
			best[r.plan] = r
	return best


def _day_payload(plan: str, day_number: int) -> dict | None:
	d = frappe.db.get_value("TOB Reading Plan Day", {"plan": plan, "day_number": day_number}, _DAY_FIELDS, as_dict=True)
	return _day_dict(d) if d else None


def _new_run(user: str, plan: str, day_numbers: list[int]):
	doc = frappe.get_doc(
		{
			"doctype": "TOB User Reading Plan",
			"user": user,
			"plan": plan,
			"status": "Active",
			"current_day": day_numbers[0] if day_numbers else 1,
			"started_at": now_datetime(),
			"schedule_start": nowdate(),
			"last_activity_at": now_datetime(),
			"completed_days": "[]",
			"completion_log": "{}",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _touch(enrollment) -> None:
	"""Any progress action: resets the "haven't seen you for a few days"
	reminder so it can fire again after the next gap."""
	enrollment.last_activity_at = now_datetime()
	enrollment.stale_nudged = 0


def _enroll_user(user: str, plan: str):
	"""Active run for (user, plan): existing, resumed (Abandoned), or new."""
	if not frappe.db.exists("TOB Reading Plan", {"name": plan, "status": "Published"}):
		frappe.throw(_("This plan isn't available."), frappe.ValidationError)
	_lock_user(user)
	day_numbers = _day_numbers(plan)
	existing = _get_active_enrollment(user, plan, for_update=True)
	if existing:
		return existing, day_numbers
	doc = _latest(user, plan, "Abandoned", for_update=True)
	if doc:
		doc.status = "Active"
		doc.current_day = next_day(_completed_days(doc), day_numbers)
		# Resume the schedule from today, at the day they're on.
		doc.schedule_start = add_days(nowdate(), -(day_numbers.index(doc.current_day) if doc.current_day in day_numbers else 0))
		_touch(doc)
		doc.save(ignore_permissions=True)
	else:
		doc = _new_run(user, plan, day_numbers)
	return doc, day_numbers


# --- browse -----------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def list_plans(age_group=None):
	filters = {"status": "Published"}
	if age_group:
		filters["age_group"] = age_group
	plans = frappe.get_all(
		"TOB Reading Plan",
		filters=filters,
		fields=[
			"name", "title", "age_group", "description", "duration_days",
			"difficulty", "icon", "accent_color", "sort_order", "category",
		],
		order_by="sort_order asc, title asc",
		ignore_permissions=True,
	)
	counts = _day_counts([p.name for p in plans])
	best = _best_rows(_user())
	readers = dict(frappe.db.sql(
		"select plan, count(distinct user) from `tabTOB User Reading Plan` where status in ('Active','Completed') group by plan"
	))

	rows = []
	for p in plans:
		row = _plan_dict(p)
		row["duration_days"] = counts.get(p.name) or p.duration_days or 0
		row["readers"] = int(readers.get(p.name) or 0)
		enrollment = best.get(p.name)
		if enrollment:
			row["enrollment_status"] = enrollment.status
			row["progress_percent"] = _percent(_completed_days(enrollment), counts.get(p.name, 0))
		else:
			row["enrollment_status"] = None
			row["progress_percent"] = 0
		rows.append(row)
	return {"plans": rows}


@frappe.whitelist(methods=["GET"])
def get_plan(plan):
	user = _user()
	p = frappe.get_doc("TOB Reading Plan", plan)
	if p.status != "Published" and "System Manager" not in frappe.get_roles():
		frappe.throw(_("This plan isn't available."), frappe.PermissionError)

	days = frappe.get_all(
		"TOB Reading Plan Day", filters={"plan": plan}, fields=_DAY_FIELDS, order_by="day_number asc",
		ignore_permissions=True,
	)
	day_numbers = [d.day_number for d in days]

	result = _plan_dict(p)
	result["duration_days"] = len(days) or p.duration_days or 0
	result["days"] = [_day_dict(d) for d in days]

	row = _best_rows(user, [plan]).get(plan)
	enrollment = frappe.get_doc("TOB User Reading Plan", row.name) if row else None
	result["enrollment"] = _enrollment_dict(enrollment, day_numbers) if enrollment else None
	# Days ticked in a run the user left — the Start button offers to pick
	# up where they left off.
	abandoned = None if enrollment else _latest(user, plan, "Abandoned")
	result["paused_progress"] = len(_completed_days(abandoned)) if abandoned else 0
	result["notes"] = {
		str(n.day_number): n.note
		for n in frappe.get_all("TOB Reading Plan Note", filters={"user": user, "plan": plan}, fields=["day_number", "note"])
		if n.note
	}
	result["group"] = _group_summary(enrollment.reading_group) if enrollment and enrollment.get("reading_group") else None
	result["in_sunday_school"] = bool(_sunday_school_group(user))
	return result


# --- progress ---------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def enroll(plan):
	doc, day_numbers = _enroll_user(_user(), plan)
	frappe.db.commit()
	return _enrollment_dict(doc, day_numbers)


@frappe.whitelist(methods=["POST"])
def restart_plan(plan):
	"""Start the plan again from Day 1. A finished run is kept as history; an
	in-progress run is reset in place."""
	if not frappe.db.exists("TOB Reading Plan", {"name": plan, "status": "Published"}):
		frappe.throw(_("This plan isn't available."), frappe.ValidationError)
	user = _user()
	_lock_user(user)
	day_numbers = _day_numbers(plan)

	doc = _get_active_enrollment(user, plan, for_update=True)
	if doc:
		doc.completed_days = "[]"
		doc.completion_log = "{}"
		doc.current_day = day_numbers[0] if day_numbers else 1
		doc.started_at = now_datetime()
		doc.schedule_start = nowdate()
		doc.completed_at = None
		_touch(doc)
		doc.save(ignore_permissions=True)
	else:
		previous = _latest(user, plan, "Completed")
		doc = _new_run(user, plan, day_numbers)
		if previous and previous.get("reading_group"):
			doc.reading_group = previous.reading_group
			doc.save(ignore_permissions=True)
	frappe.db.commit()
	return _enrollment_dict(doc, day_numbers)


@frappe.whitelist(methods=["POST"])
def mark_day_complete(plan, day_number):
	day_number = int(day_number)
	user = _user()
	_lock_user(user)
	enrollment = _require_active(user, plan)
	day_numbers = _day_numbers(plan)
	if day_number not in day_numbers:
		frappe.throw(_("That day doesn't exist on this plan."), frappe.ValidationError)

	completed = set(_completed_days(enrollment))
	already = day_number in completed
	completed.add(day_number)
	log = _log(enrollment)
	log.setdefault(str(day_number), nowdate())
	enrollment.completed_days = json.dumps(sorted(completed))
	enrollment.completion_log = json.dumps(log)
	enrollment.current_day = next_day(completed, day_numbers)
	_touch(enrollment)
	just_finished = set(day_numbers) <= completed
	if just_finished:
		enrollment.status = "Completed"
		enrollment.completed_at = now_datetime()
	enrollment.save(ignore_permissions=True)

	rewards = _reward_day(user, enrollment, day_number, just_finished) if not already else {}
	frappe.db.commit()

	if just_finished:
		from truth_of_bible.notifications.reading_plan import on_plan_completed

		on_plan_completed(user, plan)
	return {**_enrollment_dict(enrollment, day_numbers), "rewards": rewards}


def _reward_day(user: str, enrollment, day_number: int, finished: bool) -> dict:
	"""XP + reward points + badges for a ticked day (and a finished plan).
	Dedupe keys are per run + day, so unticking and re-ticking never pays
	twice. Never raises — progress is saved either way."""
	out = {"xp": 0, "points": 0, "badges": []}
	try:
		from truth_of_bible.games.arcade import progress
		from truth_of_bible.rewards import engine as rewards

		out["xp"] += progress.award_xp(
			user, DAY_XP, "reading_plan", "Reading plan day", f"plan_day:{enrollment.name}:{day_number}", enrollment.name
		)
		out["points"] += rewards._award_rule(user, "plan_day")
		if finished:
			out["xp"] += progress.award_xp(
				user, FINISH_XP, "reading_plan", "Finished a reading plan", f"plan_done:{enrollment.name}", enrollment.name
			)
			out["points"] += rewards._award_rule(user, "plan_complete", ref=enrollment.name)
		out["badges"] = [b["title"] for b in progress.check_badges(user)]
		progress.missions(user)
	except Exception:
		frappe.log_error(title="Reading plan rewards", message=frappe.get_traceback())
	return out


@frappe.whitelist(methods=["POST"])
def unmark_day(plan, day_number):
	day_number = int(day_number)
	user = _user()
	_lock_user(user)
	enrollment = _get_active_enrollment(user, plan, for_update=True)
	if not enrollment:
		# Unticking a day of a finished plan reopens that run.
		enrollment = _latest(user, plan, "Completed", for_update=True)
	if not enrollment:
		frappe.throw(_("Start this plan first."), frappe.ValidationError)

	day_numbers = _day_numbers(plan)
	completed = set(_completed_days(enrollment))
	completed.discard(day_number)
	log = _log(enrollment)
	log.pop(str(day_number), None)
	enrollment.completed_days = json.dumps(sorted(completed))
	enrollment.completion_log = json.dumps(log)
	enrollment.current_day = next_day(completed, day_numbers)
	if enrollment.status == "Completed":
		enrollment.status = "Active"
		enrollment.completed_at = None
	_touch(enrollment)
	enrollment.save(ignore_permissions=True)
	frappe.db.commit()
	return _enrollment_dict(enrollment, day_numbers)


@frappe.whitelist(methods=["POST"])
def leave_plan(plan):
	"""The run is kept (Abandoned) with its ticked days — starting the plan
	again picks up where they left off."""
	enrollment = _get_active_enrollment(_user(), plan, for_update=True)
	if not enrollment:
		return {"plan": plan, "status": "Abandoned"}
	enrollment.status = "Abandoned"
	enrollment.save(ignore_permissions=True)
	frappe.db.commit()
	return {"plan": plan, "status": "Abandoned"}


# --- habits: schedule, catch-up, reminder time, stats -------------------------


@frappe.whitelist(methods=["POST"])
def update_settings(plan, schedule_start=None, reminder_time=None, clear_reminder=0):
	"""Move the schedule's Day 1, and/or set this plan's reminder time
	('HH:MM'; `clear_reminder=1` = use the general Daily Reminder Time)."""
	user = _user()
	_lock_user(user)
	enrollment = _require_active(user, plan)
	if schedule_start:
		start = getdate(schedule_start)
		if start > getdate(add_days(nowdate(), 30)):
			frappe.throw(_("Pick a start date within the next 30 days."), frappe.ValidationError)
		enrollment.schedule_start = start
	if int(clear_reminder or 0):
		enrollment.reminder_time = None
	elif reminder_time:
		enrollment.reminder_time = get_time(reminder_time)
		enrollment.last_reminded_date = None
	enrollment.save(ignore_permissions=True)
	frappe.db.commit()
	return _enrollment_dict(enrollment, _day_numbers(plan))


@frappe.whitelist(methods=["POST"])
def catch_up(plan):
	"""Fell behind? Move the schedule so today is the day they're on. No
	days are skipped or marked — they simply continue from here."""
	user = _user()
	_lock_user(user)
	enrollment = _require_active(user, plan)
	day_numbers = _day_numbers(plan)
	index = day_numbers.index(enrollment.current_day) if enrollment.current_day in day_numbers else 0
	enrollment.schedule_start = add_days(nowdate(), -index)
	_touch(enrollment)
	enrollment.save(ignore_permissions=True)
	frappe.db.commit()
	return _enrollment_dict(enrollment, day_numbers)


@frappe.whitelist(methods=["GET"])
def get_reading_stats():
	"""Plan streak, best streak, totals and a 12-week reading calendar."""
	from truth_of_bible.reading_plans.stats import stats

	return stats(_user())


# --- reflection ---------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def save_note(plan, day_number, note=""):
	"""The user's private journal note for one day (empty deletes it).

	Never loses a note: saves for one user run one at a time (user lock),
	the existing row is re-read under that lock, and the database allows
	only one note per (user, plan, day) — so a double tap or two devices
	saving together update the same note instead of creating a second one.
	Too-long text is refused (not silently cut)."""
	user = _user()
	day_number = int(day_number)
	note = (note or "").strip()
	if len(note) > 5000:
		frappe.throw(_("That note is too long — please keep it under 5,000 characters."), frappe.ValidationError)
	_lock_user(user)
	key = {"user": user, "plan": plan, "day_number": day_number}
	row = frappe.db.sql(
		"select name from `tabTOB Reading Plan Note` where user=%s and plan=%s and day_number=%s for update",
		(user, plan, day_number),
	)
	name = row[0][0] if row else None
	if not note:
		if name:
			frappe.delete_doc("TOB Reading Plan Note", name, ignore_permissions=True)
	elif name:
		frappe.db.set_value("TOB Reading Plan Note", name, "note", note)
	else:
		if not frappe.db.exists("TOB Reading Plan Day", {"plan": plan, "day_number": day_number}):
			frappe.throw(_("That day doesn't exist on this plan."), frappe.ValidationError)
		try:
			frappe.get_doc({"doctype": "TOB Reading Plan Note", **key, "note": note}).insert(ignore_permissions=True)
		except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
			# Another save created it a moment ago — update that one.
			frappe.clear_last_message()
			frappe.db.set_value(
				"TOB Reading Plan Note", frappe.db.get_value("TOB Reading Plan Note", key, "name"), "note", note
			)
	frappe.db.commit()
	return {"plan": plan, "day_number": day_number, "note": note}


@frappe.whitelist(methods=["GET"])
def get_journal(plan=None):
	"""Every journal note (newest first), optionally for one plan."""
	filters = {"user": _user()}
	if plan:
		filters["plan"] = plan
	notes = frappe.get_all(
		"TOB Reading Plan Note", filters=filters, fields=["plan", "day_number", "note", "modified"],
		order_by="modified desc", limit_page_length=200,
	)
	titles = dict(frappe.get_all("TOB Reading Plan", filters={"name": ["in", list({n.plan for n in notes}) or [""]]},
		fields=["name", "title"], as_list=True))
	labels = {
		(r.plan, r.day_number): r.reference_label
		for r in frappe.get_all("TOB Reading Plan Day", filters={"plan": ["in", list(titles) or [""]]},
			fields=["plan", "day_number", "reference_label"])
	}
	return {"notes": [
		{"plan": n.plan, "plan_title": titles.get(n.plan, ""), "day_number": n.day_number,
		 "reference": labels.get((n.plan, n.day_number), ""), "note": n.note, "updated": str(n.modified)}
		for n in notes
	]}


# --- reading together -----------------------------------------------------------


def _new_code() -> str:
	for _i in range(20):
		code = "".join(random.choices(_CODE_ALPHABET, k=6))
		if not frappe.db.exists("TOB Reading Plan Group", {"invite_code": code}):
			return code
	frappe.throw(_("Couldn't create an invite code. Please try again."))


def _sunday_school_group(user: str) -> str | None:
	# `group` is a reserved word — quoted by hand.
	row = frappe.db.sql(
		"select `group` from `tabTOB Sunday School Profile` where user=%s and status='Active' limit 1", user
	)
	return row[0][0] if row and row[0][0] else None


def _group_summary(group: str) -> dict | None:
	g = frappe.db.get_value(
		"TOB Reading Plan Group", group, ["name", "plan", "title", "invite_code", "sunday_school_group", "owner_user"],
		as_dict=True,
	)
	if not g:
		return None
	return {
		"group": g.name, "title": g.title or "", "invite_code": g.invite_code,
		"sunday_school": bool(g.sunday_school_group),
		"members": frappe.db.count("TOB User Reading Plan", {"reading_group": g.name, "status": ["!=", "Abandoned"]}),
	}


def _attach(enrollment, group: str) -> None:
	enrollment.reading_group = group
	enrollment.save(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def create_group(plan, title=None):
	"""Start reading this plan with friends: returns an invite code."""
	user = _user()
	enrollment, day_numbers = _enroll_user(user, plan)
	if enrollment.get("reading_group"):
		frappe.db.commit()
		return _group_summary(enrollment.reading_group)
	name = frappe.db.get_value("User", user, "first_name") or "Friends"
	g = frappe.get_doc({
		"doctype": "TOB Reading Plan Group", "plan": plan, "owner_user": user,
		"title": (title or "").strip()[:80] or f"{name}'s reading group", "invite_code": _new_code(),
	}).insert(ignore_permissions=True)
	_attach(enrollment, g.name)
	frappe.db.commit()
	return _group_summary(g.name)


@frappe.whitelist(methods=["POST"])
def join_group(code):
	"""Join a friend's group by code — starts (or resumes) the plan too."""
	user = _user()
	code = (code or "").strip().upper()
	g = frappe.db.get_value("TOB Reading Plan Group", {"invite_code": code}, ["name", "plan"], as_dict=True)
	if not g:
		frappe.throw(_("That code didn't match a reading group. Check it and try again."), frappe.ValidationError)
	enrollment, _days = _enroll_user(user, g.plan)
	_attach(enrollment, g.name)
	frappe.db.commit()
	return {"plan": g.plan, "group": _group_summary(g.name)}


@frappe.whitelist(methods=["POST"])
def join_sunday_school_group(plan):
	"""Read this plan together with the user's Sunday School group — one
	shared group per (plan, Sunday School group), created on first use."""
	user = _user()
	ss = _sunday_school_group(user)
	if not ss:
		frappe.throw(_("You're not in a Sunday School group yet."), frappe.ValidationError)
	enrollment, _days = _enroll_user(user, plan)
	name = frappe.db.get_value("TOB Reading Plan Group", {"plan": plan, "sunday_school_group": ss}, "name")
	if not name:
		group_name = frappe.db.get_value("TOB Sunday School Group", ss, "group_name") or "Sunday School"
		name = frappe.get_doc({
			"doctype": "TOB Reading Plan Group", "plan": plan, "owner_user": user, "title": group_name,
			"invite_code": _new_code(), "sunday_school_group": ss,
		}).insert(ignore_permissions=True).name
	_attach(enrollment, name)
	frappe.db.commit()
	return _group_summary(name)


@frappe.whitelist(methods=["POST"])
def leave_group(plan):
	enrollment = _require_active(_user(), plan)
	enrollment.reading_group = None
	enrollment.save(ignore_permissions=True)
	frappe.db.commit()
	return {"plan": plan, "group": None}


@frappe.whitelist(methods=["GET"])
def get_group(plan):
	"""The user's group for this plan, with every member's progress."""
	user = _user()
	row = _best_rows(user, [plan]).get(plan)
	if not row or not row.get("reading_group"):
		return {"group": None, "members": []}
	members = frappe.get_all(
		"TOB User Reading Plan",
		filters={"reading_group": row.reading_group, "status": ["!=", "Abandoned"]},
		fields=["user", "status", "current_day", "completed_days", "last_activity_at"],
		order_by="modified desc",
	)
	total = len(_day_numbers(plan))
	people = {
		u.name: u for u in frappe.get_all(
			"User", filters={"name": ["in", [m.user for m in members] or [""]]}, fields=["name", "full_name", "user_image"]
		)
	}
	today = getdate(nowdate())
	out = []
	for m in members:
		done = _completed_days(m)
		u = people.get(m.user) or {}
		out.append({
			"name": u.get("full_name") or "Reader", "image": u.get("user_image"),
			"completed": len(done), "total": total, "percent": _percent(done, total),
			"current_day": m.current_day or 1, "finished": m.status == "Completed",
			"read_today": bool(m.last_activity_at and getdate(m.last_activity_at) == today),
			"is_me": m.user == user,
		})
	out.sort(key=lambda r: (-r["completed"], not r["is_me"]))
	return {"group": _group_summary(row.reading_group), "members": out}


# --- continue reading -------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def get_my_plans():
	best = _best_rows(_user())
	if not best:
		return {"plans": []}

	plan_names = list(best)
	plans = frappe.get_all(
		"TOB Reading Plan",
		filters={"name": ["in", plan_names]},
		fields=["name", "title", "age_group", "duration_days", "icon", "accent_color"],
		ignore_permissions=True,
	)
	plans_by_name = {p.name: p for p in plans}
	counts = _day_counts(plan_names)

	result = []
	# Active plans first, most recently touched first.
	ordered = sorted(best.values(), key=lambda r: r.modified, reverse=True)
	ordered.sort(key=lambda r: _STATUS_RANK[r.status])
	today = getdate(nowdate())
	for r in ordered:
		p = plans_by_name.get(r.plan)
		if not p:
			continue
		completed = _completed_days(r)
		log = _log(frappe._dict(completion_log=frappe.db.get_value("TOB User Reading Plan", r.name, "completion_log")))
		result.append({
			"plan": p.name,
			"title": p.title,
			"age_group": p.age_group,
			"icon": p.icon,
			"accent_color": p.accent_color,
			"duration_days": counts.get(p.name) or p.duration_days or 0,
			"status": r.status,
			"current_day": r.current_day or 1,
			"completed_count": len(completed),
			"progress_percent": _percent(completed, counts.get(p.name, 0)),
			"read_today": any(getdate(v) == today for v in log.values()),
			"in_group": bool(r.get("reading_group")),
			# What "Continue" opens: the plan's current day.
			"next_reading": _day_payload(p.name, r.current_day or 1) if r.status == "Active" else None,
		})
	return {"plans": result}


# --- admin: build a plan from books -----------------------------------------------


@frappe.whitelist(methods=["POST"])
def generate_days(plan, books, days, replace=0):
	"""System Manager: (re)build a plan's days from whole chapters of
	`books` ('40-43', '45-57, 19') split into `days` readings by length."""
	frappe.only_for("System Manager")
	from truth_of_bible.reading_plans.catalog import build_days, day_doc_fields, parse_books

	try:
		schedule = build_days(parse_books(books), int(days))
	except ValueError as e:
		frappe.throw(str(e), frappe.ValidationError)
	existing = frappe.get_all("TOB Reading Plan Day", filters={"plan": plan}, pluck="name")
	if existing and not int(replace or 0):
		frappe.throw(_("This plan already has days. Confirm replacing them."), frappe.ValidationError)
	for name in existing:
		frappe.delete_doc("TOB Reading Plan Day", name, ignore_permissions=True)
	for i, segs in enumerate(schedule, start=1):
		frappe.get_doc({
			"doctype": "TOB Reading Plan Day", "plan": plan,
			**day_doc_fields({"day_number": i, "title": "", "segments": segs, "reflection": ""}),
		}).insert(ignore_permissions=True)
	frappe.db.set_value("TOB Reading Plan", plan, {"duration_days": len(schedule), "generate_books": books, "generate_days": int(days)})
	frappe.db.commit()
	return {"plan": plan, "days": len(schedule)}

