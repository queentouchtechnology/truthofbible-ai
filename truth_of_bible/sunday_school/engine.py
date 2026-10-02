"""The Sunday School weekly rewards engine — a fully separate points system
from `rewards/engine.py`'s app-wide one, per the app's own explicit
requirement that the two never mix (separate doctype, separate ledger,
separate UI). The idempotent-award shape (`_lock_user`/`_ledger_has`/
`award`) mirrors `rewards/engine.py`'s `_award` pattern, since that
discipline (never pay twice on a retried request) is worth keeping
consistent — but nothing here reads or writes a `TOB Reward *` doctype.

Weeks are implicit, not a doctype: every scored row carries `week_start`
(the Monday of its ISO week, from `week_start_of`), so there's no "create
this week" admin step — leaderboards and history just filter by it.

Redemption & Expiry (this reward system only — the app-wide one never
expires): `Profile.points_clock_started_at` starts ticking the moment a
student's balance first goes positive, and is cleared by either action
below. `redeem_to_wallet` lets a student cash out their whole balance into
`TOB Reward Wallet Ledger` (the same wallet the shop/AI credits already
use — deliberately the one bridge between the two otherwise-separate
systems). `expire_stale_points`/`check_expiry_warnings`, run daily by
`notifications/sunday_school.py::daily_scan`, force the point: unredeemed
points are zeroed out `points_expiry_days` after the clock started, with
warning notifications fired at the two configured thresholds beforehand.
"""

from datetime import timedelta

import frappe
from frappe.utils import getdate, now_datetime, nowdate

_VERSE_RANK_FIELD = {1: "verse_points_1st", 2: "verse_points_2nd", 3: "verse_points_3rd"}


def week_start_of(day=None):
	day = getdate(day) if day else getdate(nowdate())
	return day - timedelta(days=day.weekday())  # Monday = 0


def settings():
	return frappe.get_cached_doc("TOB Sunday School Settings")


def get_or_create_profile(user: str):
	if not frappe.db.exists("TOB Sunday School Profile", user):
		frappe.get_doc({"doctype": "TOB Sunday School Profile", "user": user}).insert(ignore_permissions=True)
		frappe.db.commit()
	return frappe.get_doc("TOB Sunday School Profile", user)


def _lock_user(user: str) -> None:
	"""Serialises concurrent writes for one student so an idempotency check
	can't be raced past — same idiom as rewards/engine.py::_lock_user."""
	frappe.db.sql("select name from `tabUser` where name=%s for update", user)


def _ledger_has(user: str, dedupe_key: str) -> bool:
	return bool(
		frappe.db.sql(
			"select name from `tabTOB Sunday School Points Ledger` where user=%s and dedupe_key=%s limit 1 for update",
			(user, dedupe_key),
		)
	)


def balance(user: str) -> int:
	"""Current unredeemed points balance — the running sum of every ledger
	row ever posted for this user (redemptions and expiries are just
	negative rows, so this naturally nets to 0 once either happens)."""
	return int(
		frappe.db.sql("select sum(points) from `tabTOB Sunday School Points Ledger` where user=%s", (user,))[0][0] or 0
	)


def award(user: str, source: str, title: str, points: int, week_start=None, group=None, dedupe_key=None) -> bool:
	"""True if points were actually granted (False = already granted via
	this exact dedupe_key). Starts the expiry clock (Profile.points_clock_
	started_at) the moment a student's balance first goes positive — see
	the module docstring's Redemption & Expiry section."""
	week_start = week_start or week_start_of()
	dedupe_key = dedupe_key or f"{source}:{user}:{week_start}:{title}"
	_lock_user(user)
	if _ledger_has(user, dedupe_key):
		return False

	profile = get_or_create_profile(user)
	if group is None:
		group = profile.group

	balance_before = balance(user)
	frappe.get_doc(
		{
			"doctype": "TOB Sunday School Points Ledger",
			"user": user,
			"week_start": week_start,
			"source": source,
			"title": title,
			"points": points,
			"group": group,
			"dedupe_key": dedupe_key,
		}
	).insert(ignore_permissions=True)

	if points > 0 and balance_before <= 0 and not profile.points_clock_started_at:
		frappe.db.set_value("TOB Sunday School Profile", profile.name, "points_clock_started_at", now_datetime())

	frappe.db.commit()
	return True


# --- quizzes (existing LMS Quiz, assigned to Sunday School) --------------
#
# Quizzes are no longer authored here — an admin assigns an existing
# `LMS Quiz` (the same quiz doctype/take-flow/grading every app user
# already uses) to a Sunday School slot via `TOB Sunday School Quiz
# Assignment`. Taking the quiz, grading it, and showing the score all stay
# on the app's existing LMS Quiz machinery, completely untouched — this
# module only reacts to the resulting `LMS Quiz Submission` (see
# `on_lms_quiz_submission` below, called from a doc_event in hooks.py) to
# award Sunday School points, mark quiz attendance, and check the Sunday
# Goal. An assigned quiz is hidden from the app-wide quiz list forever
# (see api/quiz_visibility.py) — even once its assignment is archived, it
# stays a Sunday-School-only quiz rather than "graduating" back to public.

_QUIZ_TYPE_TO_SOURCE = {"Weekly Bible Quiz": "Weekly Quiz", "Faith Leader Exam": "Faith Leader Exam"}


def get_active_quiz_assignment(quiz_type: str, week_start=None):
	week_start = week_start or week_start_of()
	name = frappe.db.get_value(
		"TOB Sunday School Quiz Assignment",
		{"quiz_type": quiz_type, "week_start": week_start, "status": "Active"},
		"name",
	)
	return frappe.get_doc("TOB Sunday School Quiz Assignment", name) if name else None


def get_quiz_assignment_for_week(quiz_type: str, week_start):
	"""Any assignment (Active or Archived) for this slot/week, most recent
	if more than one — used for historical performance views where an
	assignment's current status no longer matters, only "which quiz was
	this week's challenge." See get_active_quiz_assignment for the
	live/current-week equivalent."""
	name = frappe.db.get_value(
		"TOB Sunday School Quiz Assignment",
		{"quiz_type": quiz_type, "week_start": week_start},
		"name", order_by="creation desc",
	)
	return frappe.get_doc("TOB Sunday School Quiz Assignment", name) if name else None


def assigned_lms_quiz_ids() -> set:
	"""Every LMS Quiz ever assigned to a Sunday School slot, Active or
	Archived — the exclusion set for the app-wide public quiz list."""
	return set(frappe.get_all("TOB Sunday School Quiz Assignment", pluck="lms_quiz"))


def on_lms_quiz_submission(user: str, lms_quiz: str, score) -> bool:
	"""Reacts to a new LMS Quiz Submission: if `lms_quiz` is this week's
	Active assignment for a Sunday School slot, awards
	quiz_points_per_mark × score as this student's first (and only)
	counted attempt for it — a resubmission of the same quiz (if the LMS
	Quiz itself allows more than one attempt) is a no-op here, matching
	the old single-attempt system's behavior; Sunday School only ever
	scores one attempt per assigned quiz per student."""
	assignment = frappe.db.get_value(
		"TOB Sunday School Quiz Assignment", {"lms_quiz": lms_quiz, "status": "Active"},
		["name", "quiz_type", "week_start"], as_dict=True,
	)
	if not assignment:
		return False

	cfg = settings()
	points = round((score or 0) * (cfg.quiz_points_per_mark or 1))
	if points <= 0:
		return False

	source = _QUIZ_TYPE_TO_SOURCE.get(assignment.quiz_type, "Weekly Quiz")
	quiz_title = frappe.db.get_value("LMS Quiz", lms_quiz, "title") or lms_quiz
	awarded = award(
		user, source, f"{quiz_title} — {score} pts", points,
		week_start=assignment.week_start, dedupe_key=f"lmsquiz:{lms_quiz}:{user}:{assignment.week_start}",
	)
	if not awarded:
		return False

	attendance = ensure_attendance(user, assignment.week_start)
	if not attendance.attended_quiz:
		attendance.attended_quiz = 1
		attendance.save(ignore_permissions=True)
		frappe.db.commit()
	check_sunday_goal(user, assignment.week_start)
	return True


# --- attendance / sunday goal ---------------------------------------------


def ensure_attendance(user: str, week_start):
	name = frappe.db.get_value("TOB Sunday School Attendance", {"user": user, "week_start": week_start}, "name")
	if name:
		return frappe.get_doc("TOB Sunday School Attendance", name)
	doc = frappe.get_doc(
		{"doctype": "TOB Sunday School Attendance", "user": user, "week_start": week_start}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc


def check_sunday_goal(user: str, week_start) -> bool:
	"""Awards the Sunday Goal bonus once class attendance + quiz attendance
	+ memory verse are all true for this student/week — guarded by
	goal_bonus_awarded so it can never double-pay."""
	attendance = ensure_attendance(user, week_start)
	if attendance.goal_bonus_awarded:
		return False
	if not (attendance.attended_class and attendance.attended_quiz and attendance.completed_memory_verse):
		return False
	cfg = settings()
	if award(user, "Sunday Goal", "Sunday Goal complete — all 3 tasks done!", cfg.sunday_goal_bonus_points,
			week_start=week_start, dedupe_key=f"goal:{user}:{week_start}"):
		attendance.goal_bonus_awarded = 1
		attendance.save(ignore_permissions=True)
		frappe.db.commit()
		return True
	return False


# --- memory verse ----------------------------------------------------------


def verify_verse_completion(completion_name: str, verified: bool, rank=None) -> dict:
	completion = frappe.get_doc("TOB Sunday School Verse Completion", completion_name)
	completion.status = "Verified" if verified else "Rejected"
	completion.rank = rank if verified else None
	completion.save(ignore_permissions=True)
	frappe.db.commit()

	if not verified:
		return {"completion": completion.name, "status": "Rejected"}

	verse = frappe.get_doc("TOB Sunday School Memory Verse", completion.memory_verse)
	cfg = settings()
	if rank in _VERSE_RANK_FIELD:
		points = cfg.get(_VERSE_RANK_FIELD[rank]) or 0
		if points:
			award(
				completion.user, "Complete Verse", f"{verse.reference} — {['1st','2nd','3rd'][rank-1]} place", points,
				week_start=verse.week_start, dedupe_key=f"verse:{completion.name}",
			)

	attendance = ensure_attendance(completion.user, verse.week_start)
	if not attendance.completed_memory_verse:
		attendance.completed_memory_verse = 1
		attendance.save(ignore_permissions=True)
		frappe.db.commit()
	check_sunday_goal(completion.user, verse.week_start)
	return {"completion": completion.name, "status": "Verified"}


# --- group bonus -------------------------------------------------------


def compute_weekly_group_bonus(week_start) -> dict:
	"""Finds the week's top-scoring group and gives each of its members a
	bonus of their own best quiz POINTS that week (Weekly Quiz or Faith
	Leader Exam — whichever scored higher) ÷ group_bonus_divisor. Points,
	not raw marks, since quiz scoring now lives entirely in the Points
	Ledger (see on_lms_quiz_submission) rather than a quiz-attempt table
	this module owns — proportionally the same ranking, just one join
	fewer. Called from the weekly reset job, or standalone via
	api/sunday_school_admin.py::mark_group_winner."""
	totals = frappe.db.sql(
		"""select `group`, sum(points) as total
		from `tabTOB Sunday School Points Ledger`
		where week_start=%s and `group` is not null and `group` != ''
		group by `group` order by total desc limit 1""",
		(week_start,), as_dict=True,
	)
	if not totals:
		return {"awarded": False, "reason": "No group has points this week."}

	top_group = totals[0]["group"]
	cfg = settings()
	divisor = cfg.group_bonus_divisor or 2
	members = frappe.get_all(
		"TOB Sunday School Profile", filters={"group": top_group, "status": "Active"}, pluck="user"
	)

	awarded_to = []
	for user in members:
		best = frappe.db.sql(
			"""select max(points) from `tabTOB Sunday School Points Ledger`
			where user=%s and week_start=%s and source in ('Weekly Quiz', 'Faith Leader Exam')""",
			(user, week_start),
		)
		best_points = best[0][0] if best else None
		if not best_points:
			continue
		bonus = round(best_points / divisor)
		if bonus <= 0:
			continue
		if award(user, "Group Bonus", "Champion Group bonus", bonus, week_start=week_start, group=top_group,
				dedupe_key=f"groupbonus:{user}:{week_start}"):
			awarded_to.append(user)

	return {"awarded": True, "group": top_group, "members": awarded_to}


# --- redemption & expiry -------------------------------------------------


def _wallet_ledger_has(user: str, dedupe_key: str) -> bool:
	return bool(
		frappe.db.sql(
			"select name from `tabTOB Reward Wallet Ledger` where user=%s and dedupe_key=%s limit 1 for update",
			(user, dedupe_key),
		)
	)


def redeem_to_wallet(user: str) -> dict:
	"""Cashes out a student's whole unredeemed weekly-rewards balance into
	their app wallet — the SAME `TOB Reward Wallet Ledger` the app-wide
	rewards/shop/AI-credit flow already uses. This is the one deliberate
	bridge between the two otherwise fully separate reward systems: earning
	stays separate, spending flows through the one wallet/shop pipeline the
	Student Dashboard already links to. Clears the expiry clock."""
	_lock_user(user)
	points = balance(user)
	if points <= 0:
		return {"redeemed": False, "reason": "No points to redeem."}

	dedupe_key = f"redeem:{user}:{now_datetime()}"
	award(user, "Redemption", "Redeemed to wallet", -points, dedupe_key=dedupe_key)

	cfg = settings()
	wallet_amount = round(points * (cfg.wallet_conversion_rate or 1), 2)
	if not _wallet_ledger_has(user, dedupe_key):
		frappe.get_doc(
			{
				"doctype": "TOB Reward Wallet Ledger",
				"user": user,
				"kind": "CONVERT",
				"title": f"Sunday School reward ({points} points)",
				"amount": wallet_amount,
				"dedupe_key": dedupe_key,
			}
		).insert(ignore_permissions=True)
		# A receipt card in the member's My Coupons, so every reward they've
		# had — Sunday School, admin cash rewards, Edenza coupons — is in one
		# list. Already USED: the money is in the wallet as of this line.
		now = now_datetime()
		frappe.get_doc(
			{
				"doctype": "TOB Reward Coupon",
				"user": user,
				"kind": "CASH",
				"code": f"SS-{frappe.generate_hash(length=8).upper()}",
				"tier": "Sunday School",
				"title": f"₹{wallet_amount:g} cash reward",
				"discount_label": f"Sunday School reward · {points} points",
				"amount": wallet_amount,
				"points_spent": points,
				"status": "USED",
				"used_on": now,
			}
		).insert(ignore_permissions=True)

	profile = get_or_create_profile(user)
	frappe.db.set_value("TOB Sunday School Profile", profile.name, "points_clock_started_at", None)
	frappe.db.commit()
	return {"redeemed": True, "points": points, "wallet_amount": wallet_amount}


def _stale_profiles():
	return frappe.get_all(
		"TOB Sunday School Profile",
		filters={"points_clock_started_at": ["is", "set"], "status": "Active"},
		fields=["name", "user", "points_clock_started_at"],
	)


def expire_stale_points() -> list:
	"""Zeroes out any student's balance whose clock has run past
	points_expiry_days, and fires SS_POINTS_EXPIRED. Called once daily —
	see notifications/sunday_school.py::daily_scan."""
	from truth_of_bible.notifications.engine import handle_event

	cfg = settings()
	expiry_days = cfg.points_expiry_days or 14
	today = getdate(nowdate())
	expired = []

	for row in _stale_profiles():
		started = getdate(row.points_clock_started_at)
		if (today - started).days < expiry_days:
			continue
		points = balance(row.user)
		if points > 0:
			if award(row.user, "Expired", "Points expired", -points, dedupe_key=f"expire:{row.user}:{today}"):
				_expired_card(row.user, points, cfg)
			handle_event("SS_POINTS_EXPIRED", row.user, {"points": points})
		frappe.db.set_value("TOB Sunday School Profile", row.name, "points_clock_started_at", None)
		frappe.db.commit()
		expired.append(row.user)

	return expired


def _expired_card(user: str, points: int, cfg) -> None:
	"""Grey "Expired" card in My Coupons for points that ran out unredeemed,
	so the member sees what they missed alongside their other rewards."""
	amount = round(points * (cfg.wallet_conversion_rate or 1), 2)
	frappe.get_doc(
		{
			"doctype": "TOB Reward Coupon",
			"user": user,
			"kind": "CASH",
			"code": f"SS-{frappe.generate_hash(length=8).upper()}",
			"tier": "Sunday School",
			"title": f"₹{amount:g} cash reward",
			"discount_label": f"Sunday School · {points} points expired",
			"amount": amount,
			"points_spent": points,
			"status": "EXPIRED",
			"expires_on": now_datetime(),
		}
	).insert(ignore_permissions=True)


# --- what students see in their points history -------------------------

_RESET_SOURCES = ("Redemption", "Expired")


def show_full_history() -> bool:
	value = settings().get("show_full_points_history")
	return True if value is None else bool(value)


def history_filters(user: str) -> dict:
	"""Points-history filters per the admin setting: everything, or only
	the rows making up the current (unredeemed, unexpired) balance — i.e.
	what came after the last redemption/expiry, which always empties the
	whole balance."""
	filters = {"user": user}
	if show_full_history():
		return filters
	last_reset = frappe.db.sql(
		"""select max(creation) from `tabTOB Sunday School Points Ledger`
		where user=%s and source in %s""",
		(user, _RESET_SOURCES),
	)[0][0]
	filters["source"] = ["not in", list(_RESET_SOURCES)]
	if last_reset:
		filters["creation"] = [">", last_reset]
	return filters


def points_summary(user: str) -> dict:
	"""Totals for the points history header."""
	rows = frappe.db.sql(
		"""select
			coalesce(sum(case when points > 0 and source not in %(reset)s then points end), 0) as earned,
			coalesce(-sum(case when source = 'Redemption' then points end), 0) as redeemed,
			coalesce(-sum(case when source = 'Expired' then points end), 0) as expired
		from `tabTOB Sunday School Points Ledger` where user=%(user)s""",
		{"user": user, "reset": _RESET_SOURCES},
		as_dict=True,
	)[0]
	return {
		"earned": int(rows.earned or 0),
		"redeemed": int(rows.redeemed or 0),
		"expired": int(rows.expired or 0),
		"available": balance(user),
	}


def available_points_card(user: str) -> dict | None:
	"""The member's current Sunday School balance as a live "available"
	card for My Coupons (not stored — it changes with every award). Tapping
	it redeems via api/sunday_school.redeem_points."""
	points = balance(user)
	if points <= 0:
		return None
	cfg = settings()
	profile = frappe.db.get_value("TOB Sunday School Profile", {"user": user}, "points_clock_started_at")
	expires = None
	days_left = 0
	if profile:
		expiry_days = cfg.points_expiry_days or 14
		expires_date = getdate(profile) + timedelta(days=expiry_days)
		days_left = max(0, (expires_date - getdate(nowdate())).days)
		expires = f"{expires_date} 23:59:00"
	return {
		"code": "SUNDAY-SCHOOL",
		"title": f"{points} Sunday School points",
		"discount_label": "Sunday School points",
		"status": "ACTIVE",
		"expires_on": expires,
		"days_left": days_left,
		"kind": "SS_POINTS",
		"amount": round(points * (cfg.wallet_conversion_rate or 1), 2),
		"points": points,
		"used_on": None,
		"created_on": None,
	}


def check_expiry_warnings() -> list:
	"""Fires SS_POINTS_EXPIRING_SOON exactly once per threshold day (an
	exact day-count match, not "<=", so a daily scan can't re-fire it every
	day within the warning window). Called once daily, before
	expire_stale_points so a student can still see a warning without ever
	missing straight to "expired" in the same run."""
	from truth_of_bible.notifications.engine import handle_event

	cfg = settings()
	expiry_days = cfg.points_expiry_days or 14
	warning_days = {d for d in (cfg.expiry_warning_days_1, cfg.expiry_warning_days_2) if d}
	today = getdate(nowdate())
	warned = []

	for row in _stale_profiles():
		started = getdate(row.points_clock_started_at)
		days_left = expiry_days - (today - started).days
		if days_left not in warning_days:
			continue
		points = balance(row.user)
		if points <= 0:
			continue
		if handle_event("SS_POINTS_EXPIRING_SOON", row.user, {"days_left": days_left, "points": points}):
			warned.append(row.user)

	return warned
