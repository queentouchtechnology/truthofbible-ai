"""Per-user "360" tabs for the admin Manage User screen — Communication,
Notifications, Error Log, Bible Reading Engagement, and AI Usage. Every
function is admin-only (`require_admin()`) and read-only, scoped to one
`user` at a time. Each function reuses whatever doctype already records
that kind of data for its own reason (WhatsApp inbox, notification engine,
core Frappe Error Log, the app's own activity/reward ledgers, the AI
gateway's usage log) — nothing here introduces new tracking, it only
re-reads it scoped to one person instead of the whole system.
"""

import json
from collections import Counter, defaultdict

import frappe
from frappe.utils import add_days, get_datetime, getdate, nowdate

from truth_of_bible.communication.auth import require_admin

_STREAK_REASONS = ("daily_checkin", "read_chapter")


# ---------------------------------------------------------------------
# 1. Communication — this user's WhatsApp thread + campaign deliveries
# ---------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def get_user_communication(user):
	require_admin()

	convo = frappe.db.get_value(
		"TOB WhatsApp Conversation",
		{"user": user},
		["name", "phone", "status", "assigned_to", "unread_count", "last_message_at", "last_message_preview"],
		as_dict=True,
	)
	messages = []
	if convo:
		messages = frappe.get_all(
			"TOB WhatsApp Message",
			filters={"conversation": convo.name},
			fields=["direction", "message_type", "message", "attachment_url", "status", "creation"],
			order_by="creation desc",
			limit_page_length=20,
		)
		assignee_name = (
			frappe.db.get_value("User", convo.assigned_to, "full_name") if convo.assigned_to else None
		)
		convo["assigned_to_name"] = assignee_name

	recipient_rows = frappe.get_all(
		"TOB Communication Campaign Recipient",
		filters={"user": user},
		fields=["campaign", "push_status", "email_status", "whatsapp_status", "error"],
		order_by="modified desc",
		limit_page_length=20,
	)
	campaign_names = [r.campaign for r in recipient_rows]
	titles = {}
	if campaign_names:
		titles = {
			c.name: c.title
			for c in frappe.get_all(
				"TOB Communication Campaign", filters={"name": ["in", campaign_names]}, fields=["name", "title"]
			)
		}
	campaigns = [
		{
			"campaign": r.campaign,
			"title": titles.get(r.campaign) or r.campaign,
			"push_status": r.push_status,
			"email_status": r.email_status,
			"whatsapp_status": r.whatsapp_status,
			"error": r.error or "",
		}
		for r in recipient_rows
	]

	return {
		"conversation": convo,
		"messages": [
			{
				"direction": m.direction,
				"message_type": m.message_type,
				"message": m.message,
				"attachment_url": m.attachment_url or "",
				"status": m.status,
				"created_at": m.creation,
			}
			for m in messages
		],
		"campaigns": campaigns,
	}


# ---------------------------------------------------------------------
# 2. Notifications — preferences + full send-log history
# ---------------------------------------------------------------------

_PREFERENCE_FIELDS = [
	"timezone",
	"bible_reading", "spiritual_growth", "bible_study", "prayer", "encouragement",
	"quiz", "courses", "community", "shopping",
	"account", "announcements", "marketing_opt_in",
	"daily_reminder_time", "quiet_hours_start", "quiet_hours_end", "max_daily_notifications",
	"preferred_prayer_time",
	"admin_new_user", "admin_support", "admin_orders", "admin_moderation", "admin_lms", "admin_system",
	"communication_center_push_opt_out", "communication_center_email_opt_out",
	"communication_center_whatsapp_opt_out",
]


@frappe.whitelist(methods=["GET"])
def get_user_notifications(user):
	require_admin()

	preferences = frappe.db.get_value(
		"TOB Notification Preference", {"user": user}, _PREFERENCE_FIELDS, as_dict=True
	)

	logs = frappe.get_all(
		"TOB Notification Send Log",
		filters={"user": user},
		fields=["event_code", "channel", "sent_at", "tracked", "devices_reached", "devices_failed", "failure_reason"],
		order_by="sent_at desc",
		limit_page_length=50,
	)

	total_sent = len(logs)
	total_delivered = sum(1 for row in logs if (row.devices_reached or 0) > 0)
	total_failed = sum(1 for row in logs if (row.devices_failed or 0) > 0 and (row.devices_reached or 0) == 0)

	return {
		"preferences": preferences,
		"send_log": logs,
		"total_sent": total_sent,
		"total_delivered": total_delivered,
		"total_failed": total_failed,
	}


# ---------------------------------------------------------------------
# 3. Error Log — errors that occurred in this user's own session
# ---------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def get_user_error_logs(user, limit=30):
	require_admin()
	limit = max(1, min(int(limit), 100))

	rows = frappe.get_all(
		"Error Log",
		filters={"owner": user},
		fields=["name", "method", "error", "creation"],
		order_by="creation desc",
		limit_page_length=limit,
	)
	for r in rows:
		full = r.error or ""
		r["error"] = full[:500]
		r["truncated"] = len(full) > 500

	return {"logs": rows, "total_count": frappe.db.count("Error Log", {"owner": user})}


# ---------------------------------------------------------------------
# 4. Bible Reading Engagement — this user's own reading + plans + streak
# ---------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def get_user_reading_engagement(user, days=30):
	require_admin()
	days = max(1, min(int(days), 180))
	since = add_days(nowdate(), -(days - 1))

	rows = frappe.get_all(
		"TOB User Activity Event",
		filters={"user": user, "event": "verse_opened", "event_time": [">=", since]},
		fields=["event_time", "data"],
	)

	daily = defaultdict(int)
	book_counter = Counter()
	for r in rows:
		daily[getdate(r.event_time).isoformat()] += 1
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

	daily_series = [{"date": d, "chapters_read": c} for d, c in sorted(daily.items())]
	top_books = [{"book_id": b, "count": c} for b, c in book_counter.most_common(10)]

	streak_rows = frappe.db.sql(
		"""
		select distinct date(creation) as day
		from `tabTOB Reward Ledger`
		where user=%s and reason in %s and creation >= %s
		""",
		(user, _STREAK_REASONS, add_days(nowdate(), -120)),
		as_dict=True,
	)
	streak_days = {getdate(r.day) for r in streak_rows}
	today = getdate(nowdate())
	cursor = today if today in streak_days else add_days(today, -1)
	current_streak = 0
	while cursor in streak_days:
		current_streak += 1
		cursor = add_days(cursor, -1)

	enrollments = frappe.get_all(
		"TOB User Reading Plan",
		filters={"user": user, "status": ["!=", "Abandoned"]},
		fields=["plan", "status", "current_day", "completed_days"],
		order_by="modified desc",
	)
	plan_names = [e.plan for e in enrollments]
	plans_by_name = {}
	if plan_names:
		plans_by_name = {
			p.name: p
			for p in frappe.get_all(
				"TOB Reading Plan",
				filters={"name": ["in", plan_names]},
				fields=["name", "title", "age_group", "duration_days", "icon", "accent_color"],
			)
		}
	reading_plans = []
	for e in enrollments:
		p = plans_by_name.get(e.plan)
		if not p:
			continue
		try:
			completed = json.loads(e.completed_days or "[]")
		except Exception:
			completed = []
		progress = round(len(completed) / p.duration_days * 100) if p.duration_days else 0
		reading_plans.append(
			{
				"plan": p.name,
				"title": p.title,
				"age_group": p.age_group,
				"icon": p.icon,
				"accent_color": p.accent_color,
				"status": e.status,
				"current_day": e.current_day,
				"progress_percent": progress,
			}
		)

	return {
		"days": days,
		"total_chapters_read": sum(daily.values()),
		"current_streak": current_streak,
		"daily_series": daily_series,
		"top_books": top_books,
		"reading_plans": reading_plans,
	}


# ---------------------------------------------------------------------
# 5. AI Usage — tokens/cost today, yesterday, this month, + date filter
# ---------------------------------------------------------------------


def _usage_totals(user: str, start, end) -> dict:
	row = frappe.db.sql(
		"""
		select
			coalesce(sum(total_tokens), 0) as tokens,
			coalesce(sum(estimated_cost_usd), 0) as cost,
			count(*) as calls
		from `tabTOB AI Usage Log`
		where user=%s and date(creation) between %s and %s
		""",
		(user, start, end),
		as_dict=True,
	)
	r = row[0] if row else {}
	return {
		"tokens": int(r.get("tokens") or 0),
		"cost_usd": float(r.get("cost") or 0),
		"calls": int(r.get("calls") or 0),
	}


@frappe.whitelist(methods=["GET"])
def get_user_ai_usage(user, start_date=None, end_date=None):
	require_admin()

	today = getdate(nowdate())
	yesterday = add_days(today, -1)
	month_start = today.replace(day=1)

	quick_stats = {
		"today": _usage_totals(user, today, today),
		"yesterday": _usage_totals(user, yesterday, yesterday),
		"this_month": _usage_totals(user, month_start, today),
	}

	range_start = getdate(start_date) if start_date else add_days(today, -29)
	range_end = getdate(end_date) if end_date else today
	if range_start > range_end:
		range_start, range_end = range_end, range_start

	rows = frappe.get_all(
		"TOB AI Usage Log",
		filters={"user": user, "creation": ["between", [get_datetime(f"{range_start} 00:00:00"), get_datetime(f"{range_end} 23:59:59")]]},
		fields=["task", "provider", "model", "total_tokens", "estimated_cost_usd", "status", "creation"],
		order_by="creation desc",
	)

	daily = defaultdict(lambda: {"tokens": 0, "calls": 0})
	task_tokens = Counter()
	task_calls = Counter()
	range_tokens = 0
	range_cost = 0.0
	for r in rows:
		day = getdate(r.creation).isoformat()
		daily[day]["tokens"] += r.total_tokens or 0
		daily[day]["calls"] += 1
		task_tokens[r.task or "unknown"] += r.total_tokens or 0
		task_calls[r.task or "unknown"] += 1
		range_tokens += r.total_tokens or 0
		range_cost += float(r.estimated_cost_usd or 0)

	daily_series = [{"date": d, "tokens": v["tokens"], "calls": v["calls"]} for d, v in sorted(daily.items())]
	by_task = [
		{"task": t, "tokens": task_tokens[t], "calls": task_calls[t]}
		for t, _ in task_tokens.most_common(10)
	]

	return {
		"quick_stats": quick_stats,
		"range_start": range_start.isoformat(),
		"range_end": range_end.isoformat(),
		"range_tokens": range_tokens,
		"range_cost_usd": range_cost,
		"range_calls": len(rows),
		"daily_series": daily_series,
		"by_task": by_task,
		"recent_calls": [
			{
				"task": r.task,
				"provider": r.provider,
				"model": r.model,
				"total_tokens": r.total_tokens or 0,
				"estimated_cost_usd": r.estimated_cost_usd or 0,
				"status": r.status,
				"created_at": r.creation,
			}
			for r in rows[:50]
		],
	}
