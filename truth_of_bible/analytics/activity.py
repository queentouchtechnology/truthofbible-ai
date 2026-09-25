"""Lightweight custom activity log — records only a small, curated set of
in-app events (see `_ALLOWED_EVENTS`) against the real logged-in user, so
an admin can see "who did what" with their name/avatar in one place. This
is deliberately separate from Firebase/GA4 (Flutter's own
AppAnalyticsService/ActivityQueueService), which stays the aggregate,
product-analytics engine — GA4 has no per-user drill-down or avatars
surfaced anywhere reachable from inside this app. This module exists only
for that customer-level report; it is not a general-purpose event sink —
see the Flutter-side queue's own matching curated event list before adding
a new event name here.

Auth: session-cookie, the logged-in end user's own Frappe session — same
mechanism `bible.qa`/`bible.explain` already use (see
bible_ai_remote_service.dart's `_sessionOptions`), NOT the shared admin
erpToken the Social Intelligence/Communication Center screens use.
`frappe.session.user` is the sole source of truth for whose activity this
is; a client-supplied user id is never trusted, unlike some older
endpoints in this app (e.g. GetUserRequest.userId) — this module doesn't
follow that precedent on purpose, since misattributed activity data would
directly undermine the report this exists to build.
"""

import json

import frappe
from frappe.utils import get_datetime, now_datetime

from truth_of_bible.communication.auth import require_admin

# Kept in lockstep with ActivityQueueService's own curated list in the
# Flutter app — add to both sides together. Silently rejecting anything
# else here means a stray/typo'd event name from a client never becomes a
# permanent row (or a KeyError) — it's just dropped, same "silent failure"
# principle as the queue's own upload behavior.
_ALLOWED_EVENTS = {
	"bible_search",
	"verse_opened",
	"ai_bible_qa",
	"ai_verse_explanation",
	"quiz_started",
	"quiz_completed",
	"bookmark_added",
	"course_enrolled",
	"prayer_topic_explored",
	"devotional_viewed",
	"login_success",
	"signup_success",
	"donation_completed",
	# Reported by the app against a notification's send_id — see
	# notifications/engagement.py.
	"notification_received",
	"notification_tapped",
}

_MAX_BATCH_SIZE = 100


def _to_site_naive(value):
	"""The app sends ISO 8601 timestamps with a "Z" (UTC) suffix, which
	parse as timezone-aware. Frappe stores naive datetimes in the site's
	timezone, and MariaDB rejects an aware value outright ("Incorrect
	datetime value: '...+00:00'") — every batch containing a timestamp
	used to fail on insert. Converts to the site timezone, then drops
	tzinfo, so event_time matches every other Frappe timestamp."""
	if value.tzinfo is None:
		return value
	try:
		from zoneinfo import ZoneInfo

		from frappe.utils import get_system_timezone

		return value.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)
	except Exception:
		# Never let a timezone lookup drop the event — keep the instant,
		# just without tz conversion (off by the site's UTC offset at worst).
		return value.replace(tzinfo=None)


@frappe.whitelist(methods=["POST"])
def record_batch(events):
	"""Bulk-records one client-flushed batch of curated events for the
	logged-in user. A bad row (unknown event name, malformed shape, a
	single insert failing) is skipped, never raised — this must not give
	the Flutter queue a reason to retry (it doesn't retry at all, by
	design) or surface an error anywhere near a real user action."""
	user = frappe.session.user
	if user == "Guest":
		return {"recorded": 0}

	rows = events
	if isinstance(rows, str):
		try:
			rows = json.loads(rows)
		except Exception:
			return {"recorded": 0}
	if not isinstance(rows, list):
		return {"recorded": 0}

	recorded = 0
	failed = 0
	last_traceback = ""
	for row in rows[:_MAX_BATCH_SIZE]:
		if not isinstance(row, dict):
			continue
		event_name = row.get("event")
		if event_name not in _ALLOWED_EVENTS:
			continue

		event_time = row.get("event_time")
		try:
			event_time = _to_site_naive(get_datetime(event_time)) if event_time else now_datetime()
		except Exception:
			event_time = now_datetime()

		try:
			frappe.get_doc({
				"doctype": "TOB User Activity Event",
				"user": user,
				"event": event_name,
				"event_time": event_time,
				"data": json.dumps(row.get("data") or {}),
			}).insert(ignore_permissions=True)
			recorded += 1
		except Exception:
			# One entry per BATCH, not per event — a systemic failure (like
			# the timezone bug this replaced) used to write up to 100
			# near-identical full tracebacks per request and bury every other
			# error in the log.
			failed += 1
			last_traceback = frappe.get_traceback()
			continue

	if failed:
		frappe.log_error(
			title=f"analytics.record_batch: {failed} event(s) failed to insert",
			message=last_traceback,
		)

	return {"recorded": recorded}


@frappe.whitelist(methods=["GET"])
def get_activity_users(limit=50, offset=0, search=None):
	"""Admin-only — one row per user who has any recorded activity, with
	their real name/avatar (from the core User doctype) plus a total event
	count and last-active time. Powers the admin report's top-level user
	list — the actual "who did what, with avatars" view."""
	require_admin()

	conditions = ""
	values = {"limit": int(limit), "offset": int(offset)}
	if search:
		conditions = "and (u.full_name like %(search)s or a.user like %(search)s)"
		values["search"] = f"%{search}%"

	rows = frappe.db.sql(
		f"""
		select
			a.user as user,
			u.full_name as full_name,
			u.user_image as user_image,
			count(*) as event_count,
			max(a.event_time) as last_active
		from `tabTOB User Activity Event` a
		left join `tabUser` u on u.name = a.user
		where 1=1 {conditions}
		group by a.user
		order by last_active desc
		limit %(limit)s offset %(offset)s
		""",
		values,
		as_dict=True,
	)

	total_row = frappe.db.sql(
		f"""
		select count(distinct a.user) as total
		from `tabTOB User Activity Event` a
		left join `tabUser` u on u.name = a.user
		where 1=1 {conditions}
		""",
		values,
		as_dict=True,
	)

	return {"users": rows, "total_count": total_row[0]["total"] if total_row else 0}


@frappe.whitelist(methods=["GET"])
def get_user_activity(user, limit=50, offset=0):
	"""Admin-only — one user's own event timeline, newest first, each row's
	`data` parsed back from JSON for direct display. The drill-down behind
	tapping a user in the admin report's list."""
	require_admin()

	rows = frappe.get_all(
		"TOB User Activity Event",
		filters={"user": user},
		fields=["event", "event_time", "data"],
		order_by="event_time desc",
		limit_page_length=int(limit),
		limit_start=int(offset),
	)
	for row in rows:
		try:
			row["data"] = json.loads(row["data"]) if row["data"] else {}
		except Exception:
			row["data"] = {}

	user_doc = frappe.db.get_value(
		"User", user, ["full_name", "user_image"], as_dict=True
	) or {}

	return {
		"user": user,
		"full_name": user_doc.get("full_name"),
		"user_image": user_doc.get("user_image"),
		"events": rows,
		"total_count": frappe.db.count("TOB User Activity Event", {"user": user}),
	}


@frappe.whitelist(methods=["GET"])
def get_activity_summary():
	"""Admin-only — overall counts per event type, for a small totals strip
	above the per-user list (e.g. '4,595 verse_opened this month')."""
	require_admin()

	rows = frappe.db.sql(
		"""
		select event, count(*) as count
		from `tabTOB User Activity Event`
		group by event
		order by count desc
		""",
		as_dict=True,
	)
	return {"events": rows}


@frappe.whitelist(methods=["GET"])
def get_event_users(event, limit=50):
	"""Admin-only — which users performed one event, with how many times
	and when last (real names/avatars from the core User doctype). The
	"which user did which event" view: the summary strip lists event
	types, tapping one lands here."""
	require_admin()

	rows = frappe.db.sql(
		"""
		select
			a.user as user,
			u.full_name as full_name,
			u.user_image as user_image,
			count(*) as event_count,
			max(a.event_time) as last_active
		from `tabTOB User Activity Event` a
		left join `tabUser` u on u.name = a.user
		where a.event = %(event)s
		group by a.user
		order by event_count desc, last_active desc
		limit %(limit)s
		""",
		{"event": event, "limit": int(limit)},
		as_dict=True,
	)
	return {"event": event, "users": rows}
