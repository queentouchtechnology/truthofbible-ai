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

import json
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


# --- quizzes -------------------------------------------------------------


def finalize_quiz(quiz_name: str) -> dict:
	"""Grades every TOB Sunday School Quiz Attempt for this quiz against
	TOB Sunday School Weekly Quiz Question.correct_option server-side
	(never trusts a client-supplied score), ranks attempts by score desc
	(ties broken by earliest submission), awards quiz_points_per_mark ×
	score to every attempt, and closes the quiz."""
	quiz = frappe.get_doc("TOB Sunday School Weekly Quiz", quiz_name)
	questions = frappe.get_all(
		"TOB Sunday School Weekly Quiz Question",
		filters={"quiz": quiz_name},
		fields=["name", "question_number", "correct_option", "marks"],
		order_by="question_number asc",
	)
	total_marks = sum(q.marks or 0 for q in questions)
	answer_key = [q.correct_option for q in questions]
	marks_seq = [q.marks or 0 for q in questions]

	attempts = frappe.get_all(
		"TOB Sunday School Quiz Attempt",
		filters={"quiz": quiz_name},
		fields=["name", "user", "answers", "submitted_at"],
		order_by="submitted_at asc",
	)

	cfg = settings()
	scored = []
	for a in attempts:
		try:
			given = json.loads(a.answers or "[]")
		except Exception:
			given = []
		score = 0
		for i, correct in enumerate(answer_key):
			if i < len(given) and given[i] == correct:
				score += marks_seq[i]
		scored.append({"name": a.name, "user": a.user, "score": score, "submitted_at": a.submitted_at})

	scored.sort(key=lambda r: (-r["score"], r["submitted_at"] or now_datetime()))

	rank = 0
	last_score = None
	for i, row in enumerate(scored):
		if row["score"] != last_score:
			rank = i + 1
			last_score = row["score"]
		frappe.db.set_value(
			"TOB Sunday School Quiz Attempt", row["name"],
			{"score": row["score"], "total_marks": total_marks, "rank": rank},
		)
		points = round(row["score"] * (cfg.quiz_points_per_mark or 1))
		source = "Faith Leader Exam" if quiz.quiz_type == "Faith Leader Exam" else "Weekly Quiz"
		award(
			row["user"], source, f"{quiz.title} — {row['score']}/{total_marks}", points,
			week_start=quiz.week_start, dedupe_key=f"quiz:{quiz.name}:{row['user']}",
		)

	quiz.status = "Closed"
	quiz.total_marks = total_marks
	quiz.save(ignore_permissions=True)
	frappe.db.commit()
	return {"quiz": quiz.name, "attempts_graded": len(scored)}


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
	bonus of their own best quiz score that week ÷ group_bonus_divisor.
	Called from the weekly reset job, after finalize_quiz has already run
	for the week's quizzes."""
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
			"""select qa.score from `tabTOB Sunday School Quiz Attempt` qa
			join `tabTOB Sunday School Weekly Quiz` q on q.name = qa.quiz
			where qa.user=%s and q.week_start=%s and qa.score is not null
			order by qa.score desc limit 1""",
			(user, week_start),
		)
		if not best:
			continue
		bonus = round(best[0][0] / divisor)
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
				"title": "Wallet updated via reward coupon redeemed",
				"amount": wallet_amount,
				"dedupe_key": dedupe_key,
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
			award(row.user, "Expired", "Points expired", -points, dedupe_key=f"expire:{row.user}:{today}")
			handle_event("SS_POINTS_EXPIRED", row.user, {"points": points})
		frappe.db.set_value("TOB Sunday School Profile", row.name, "points_clock_started_at", None)
		frappe.db.commit()
		expired.append(row.user)

	return expired


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
