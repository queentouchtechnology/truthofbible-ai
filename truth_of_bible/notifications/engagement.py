"""Notification engagement report: delivery → tap → what the person did
next. Builds on the event chain, not a single "read" flag:

    send (engine, recorded with a send_id)
      → accepted by Google's push service (devices_reached on the send row)
      → received in the foreground (app event `notification_received`)
      → tapped (app event `notification_tapped`, carries the send_id)
      → actions within 30 minutes (the app's existing curated activity
        events: verse opened, quiz started, AI question, ...)

What this can and can't say — kept visible in the UI:

- "Delivered" means ACCEPTED by Google's push service. FCM gives no
  delivery or read receipts, and a notification shown while the app is in
  the background runs no app code, so "received" is only recorded when the
  app was in the foreground. Taps are recorded reliably.
- Only sends made after this shipped carry a send_id (`tracked = 1`), and
  only people on an app version that reports taps can register one — so
  early open rates are a floor, not the true figure.
- "Engaged" means at least one recorded action within ENGAGEMENT_WINDOW_MIN
  of the tap — a proxy, not a promise the app was open that whole time.
  Real session length (`app_session_ended`, reported by `main.dart`'s
  WidgetsBindingObserver) is now measured alongside it where available —
  same phased-rollout caveat as taps: only counted for a tap whose user is
  on an app version that reports session length at all.
"""

import json

import frappe
from frappe.utils import add_days, get_datetime, now_datetime, nowdate

from truth_of_bible.communication.auth import require_admin

_PERIODS = ("today", "yesterday", "7d", "30d", "90d")
ENGAGEMENT_WINDOW_MIN = 30
_IGNORED_AFTER_HOURS = 24  # a send is "ignored" once this long passes with no tap
_NON_ACTION_EVENTS = ("notification_received", "notification_tapped", "login_success")

_ACTION_LABELS = {
	"verse_opened": "Read a chapter",
	"bible_search": "Searched the Bible",
	"ai_bible_qa": "Asked the AI a question",
	"ai_verse_explanation": "Asked the AI to explain a verse",
	"quiz_started": "Started a quiz",
	"quiz_completed": "Completed a quiz",
	"bookmark_added": "Bookmarked a verse",
	"course_enrolled": "Enrolled in a course",
	"prayer_topic_explored": "Explored a prayer topic",
	"devotional_viewed": "Read a devotional",
	"signup_success": "Signed up",
	"donation_completed": "Donated",
}


def _range(period: str):
	today = get_datetime(nowdate())
	if period == "today":
		return today, add_days(today, 1)
	if period == "yesterday":
		return add_days(today, -1), today
	days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 7)
	return add_days(today, -(days - 1)), add_days(today, 1)


def _send_id(data):
	try:
		return (json.loads(data) if isinstance(data, str) else data or {}).get("send_id")
	except Exception:
		return None


def _session_seconds(data):
	try:
		value = (json.loads(data) if isinstance(data, str) else data or {}).get("duration_seconds")
		return int(value) if value is not None else None
	except Exception:
		return None


class _Ctx:
	def __init__(self, period: str):
		self.period = period if period in _PERIODS else "7d"
		self.start, self.end = _range(self.period)
		self.now = now_datetime()

		self.sends = frappe.get_all(
			"TOB Notification Send Log",
			filters={
				"channel": "PUSH",
				"tracked": 1,
				"sent_at": ["between", [self.start, self.end]],
			},
			fields=["name", "user", "event_code", "sent_at", "devices_reached", "devices_failed", "failure_reason"],
			order_by="sent_at asc",
		)
		ids = {s.name for s in self.sends}

		# Taps/receipts can arrive after the period ends, so no upper bound.
		rows = frappe.get_all(
			"TOB User Activity Event",
			filters={"event": ["in", ["notification_received", "notification_tapped"]], "event_time": [">=", self.start]},
			fields=["user", "event", "event_time", "data"],
			order_by="event_time asc",
		)
		self.received = {}
		self.tapped = {}
		for r in rows:
			sid = _send_id(r.data)
			if sid in ids:
				bucket = self.tapped if r.event == "notification_tapped" else self.received
				bucket.setdefault(sid, r.event_time)  # first one wins

		# Activity within the window after each tap — attributed to that send.
		self.actions = {}
		if self.tapped:
			users = list({s.user for s in self.sends if s.name in self.tapped})
			earliest = min(self.tapped.values())
			acts = frappe.get_all(
				"TOB User Activity Event",
				filters={
					"user": ["in", users],
					"event": ["not in", list(_NON_ACTION_EVENTS)],
					"event_time": [">=", earliest],
				},
				fields=["user", "event", "event_time"],
				order_by="event_time asc",
			)
			by_user = {}
			for a in acts:
				by_user.setdefault(a.user, []).append(a)
			for s in self.sends:
				tap = self.tapped.get(s.name)
				if not tap:
					continue
				limit = tap + _minutes(ENGAGEMENT_WINDOW_MIN)
				self.actions[s.name] = [a.event for a in by_user.get(s.user, []) if tap <= a.event_time <= limit]

		# Real session length after a tap, from the app's own session-end
		# report (`app_session_ended`, `data.duration_seconds` — see
		# `main.dart`'s WidgetsBindingObserver). The first session-end
		# reported after the tap is the session the tap opened or continued.
		# Only sends whose user is on an app version that reports this at
		# all will have one — same phased-rollout caveat as taps themselves.
		self.session_seconds = {}
		if self.tapped:
			sessions = frappe.get_all(
				"TOB User Activity Event",
				filters={
					"user": ["in", users],
					"event": "app_session_ended",
					"event_time": [">=", earliest],
				},
				fields=["user", "event_time", "data"],
				order_by="event_time asc",
			)
			by_user_sessions = {}
			for row in sessions:
				by_user_sessions.setdefault(row.user, []).append(row)
			for s in self.sends:
				tap = self.tapped.get(s.name)
				if not tap:
					continue
				for row in by_user_sessions.get(s.user, []):
					if row.event_time >= tap:
						seconds = _session_seconds(row.data)
						if seconds is not None:
							self.session_seconds[s.name] = seconds
						break

	def accepted(self, s) -> bool:
		return bool(s.devices_reached and s.devices_reached > 0)

	def is_ignored(self, s) -> bool:
		if s.name in self.tapped or not self.accepted(s):
			return False
		return (self.now - get_datetime(s.sent_at)).total_seconds() >= _IGNORED_AFTER_HOURS * 3600


def _minutes(n):
	from datetime import timedelta

	return timedelta(minutes=n)


def _rate(part, whole):
	return round(100 * part / whole, 1) if whole else 0


def _bucket(seconds: float) -> str:
	if seconds < 60:
		return "under_1_min"
	if seconds < 3600:
		return "under_1_hour"
	if seconds < 86400:
		return "several_hours"
	return "next_day_or_later"


_BUCKET_LABELS = {
	"under_1_min": "Opened within a minute",
	"under_1_hour": "Within an hour",
	"several_hours": "After several hours",
	"next_day_or_later": "The next day or later",
}


@frappe.whitelist(methods=["GET"])
def get_engagement_report(period="7d"):
	require_admin()
	ctx = _Ctx(period)
	titles = {t.name: t.title for t in frappe.get_all("TOB Notification Template", fields=["name", "title"])}
	# A campaign push's `event_code` is the campaign's own doc name, not a
	# template — without this, every campaign row in `by_type` would show
	# as a raw id instead of the campaign's actual name.
	titles.update(
		{c.name: c.campaign_name for c in frappe.get_all("TOB Communication Campaign", fields=["name", "campaign_name"])}
	)

	sent = len(ctx.sends)
	accepted = [s for s in ctx.sends if ctx.accepted(s)]
	failed = [s for s in ctx.sends if not ctx.accepted(s)]
	tapped = [s for s in accepted if s.name in ctx.tapped]
	ignored = [s for s in accepted if ctx.is_ignored(s)]
	pending = len(accepted) - len(tapped) - len(ignored)

	reasons = {}
	for s in failed:
		reasons[s.failure_reason or "Unknown"] = reasons.get(s.failure_reason or "Unknown", 0) + 1

	buckets = {k: 0 for k in _BUCKET_LABELS}
	for s in tapped:
		seconds = (get_datetime(ctx.tapped[s.name]) - get_datetime(s.sent_at)).total_seconds()
		buckets[_bucket(max(seconds, 0))] += 1

	engaged = [s for s in tapped if ctx.actions.get(s.name)]
	action_counts = {}
	for s in engaged:
		for ev in set(ctx.actions[s.name]):
			action_counts[ev] = action_counts.get(ev, 0) + 1

	session_lengths = [ctx.session_seconds[s.name] for s in tapped if s.name in ctx.session_seconds]

	by_type = {}
	for s in ctx.sends:
		row = by_type.setdefault(
			s.event_code,
			{"event": s.event_code, "title": titles.get(s.event_code) or s.event_code,
			 "sent": 0, "accepted": 0, "tapped": 0, "engaged": 0},
		)
		row["sent"] += 1
		if ctx.accepted(s):
			row["accepted"] += 1
			if s.name in ctx.tapped:
				row["tapped"] += 1
				if ctx.actions.get(s.name):
					row["engaged"] += 1
	type_rows = sorted(by_type.values(), key=lambda r: -r["sent"])
	for r in type_rows:
		r["tap_rate"] = _rate(r["tapped"], r["accepted"])

	segments = _segments(ctx)
	reengagement = _reengagement(ctx)
	first_event = frappe.db.sql(
		"select min(event_time) from `tabTOB User Activity Event` where event = 'notification_tapped'"
	)[0][0]

	return {
		"period": ctx.period,
		"range": {"start": str(ctx.start.date()), "end": str(add_days(ctx.end, -1).date())},
		"tracking_started": str(first_event) if first_event else None,
		"delivery": {
			"sent": sent,
			"accepted": len(accepted),
			"failed": len(failed),
			"delivery_rate": _rate(len(accepted), sent),
			"failure_reasons": [{"reason": k, "count": v} for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])],
			"foreground_received": len([s for s in accepted if s.name in ctx.received]),
		},
		"reading": {
			"tapped": len(tapped),
			"tap_rate": _rate(len(tapped), len(accepted)),
			"ignored": len(ignored),
			"pending": max(pending, 0),
			"time_to_open": [{"key": k, "label": _BUCKET_LABELS[k], "count": v} for k, v in buckets.items()],
		},
		"engagement": {
			"engaged": len(engaged),
			"engagement_rate": _rate(len(engaged), len(tapped)),
			"window_minutes": ENGAGEMENT_WINDOW_MIN,
			"actions": [
				{"event": k, "label": _ACTION_LABELS.get(k, k), "count": v}
				for k, v in sorted(action_counts.items(), key=lambda kv: -kv[1])
			],
			"avg_session_seconds": round(sum(session_lengths) / len(session_lengths)) if session_lengths else None,
			"sessions_measured": len(session_lengths),
		},
		"funnel": [
			{"label": "Sent", "count": sent},
			{"label": "Accepted by Google", "count": len(accepted)},
			{"label": "Tapped", "count": len(tapped)},
			{"label": f"Acted within {ENGAGEMENT_WINDOW_MIN} min", "count": len(engaged)},
		],
		"by_type": type_rows,
		"segments": [{"key": k, "label": v["label"], "count": len(v["users"])} for k, v in segments.items()],
		"reengagement": reengagement,
		"suggestions": _suggestions(sent, accepted, tapped, engaged, failed, segments, reasons, first_event),
		"note": (
			"'Delivered' means accepted by Google's push service — it gives no delivery or read receipts. "
			"Taps come from the app, so they cover only people on an updated app version; treat early open "
			"rates as a floor. Session length is only counted for taps from an app version that reports it — "
			"treat it the same way."
		),
	}


_DORMANT_DAYS = 7  # no real activity for this long before a send = dormant
_REENGAGE_WINDOW_HOURS = 48  # real activity within this long after = "came back"


def _reengagement(ctx: "_Ctx") -> dict:
	"""Of the notifications sent to someone who'd gone quiet, how many
	actually brought them back? Built from real `TOB User Activity Event`
	history rather than `User.last_active` (which only ever reflects NOW,
	not who was dormant at the moment a past send went out — the same
	limitation notifications/insights.py's own segments already carry)."""
	accepted = [s for s in ctx.sends if ctx.accepted(s)]
	if not accepted:
		return {"dormant_sends": 0, "reengaged": 0, "rate": 0}

	users = list({s.user for s in accepted})
	real_events = [e for e in _ACTION_LABELS] + ["app_session_ended"]
	history = frappe.get_all(
		"TOB User Activity Event",
		filters={"user": ["in", users], "event": ["in", real_events]},
		fields=["user", "event_time"],
		order_by="event_time asc",
	)
	by_user = {}
	for row in history:
		by_user.setdefault(row.user, []).append(row.event_time)

	dormant_sends = 0
	reengaged_users = set()
	for s in accepted:
		times = by_user.get(s.user, [])
		sent = get_datetime(s.sent_at)
		prior = max((t for t in times if t < sent), default=None)
		if prior is not None and (sent - prior).days < _DORMANT_DAYS:
			continue  # already active recently — not a re-engagement case
		dormant_sends += 1
		came_back = any(sent < t <= sent + _hours(_REENGAGE_WINDOW_HOURS) for t in times)
		if came_back:
			reengaged_users.add(s.user)

	return {
		"dormant_sends": dormant_sends,
		"reengaged": len(reengaged_users),
		"rate": _rate(len(reengaged_users), dormant_sends),
		"dormant_days": _DORMANT_DAYS,
		"window_hours": _REENGAGE_WINDOW_HOURS,
	}


def _hours(n):
	from datetime import timedelta

	return timedelta(hours=n)


def _segments(ctx: "_Ctx"):
	"""Who isn't responding — from every tracked, accepted send in the period."""
	per_user = {}
	for s in ctx.sends:
		if ctx.accepted(s):
			per_user.setdefault(s.user, []).append(s)

	out = {
		"never_tapped": {"label": "Received several, never tapped one", "users": []},
		"repeatedly_ignored": {"label": "Ignored their last 5 notifications", "users": []},
		"tap_no_action": {"label": "Tap, but do nothing in the app", "users": []},
		"responsive": {"label": "Tap most notifications (30%+)", "users": []},
		"failed": {"label": "Push failing (token invalid or unreachable)", "users": []},
	}
	for user, sends in per_user.items():
		taps = [s for s in sends if s.name in ctx.tapped]
		if len(sends) >= 3 and not taps:
			out["never_tapped"]["users"].append(user)
		last5 = sends[-5:]
		if len(last5) == 5 and all(s.name not in ctx.tapped and ctx.is_ignored(s) for s in last5):
			out["repeatedly_ignored"]["users"].append(user)
		if taps and all(not ctx.actions.get(s.name) for s in taps):
			out["tap_no_action"]["users"].append(user)
		if len(sends) >= 3 and len(taps) / len(sends) >= 0.3:
			out["responsive"]["users"].append(user)
	for s in ctx.sends:
		if not ctx.accepted(s) and s.user not in out["failed"]["users"]:
			out["failed"]["users"].append(s.user)
	return out


def _suggestions(sent, accepted, tapped, engaged, failed, segments, reasons, first_event):
	out = []
	if not first_event:
		out.append({
			"title": "Tap tracking hasn't started reporting yet",
			"detail": "No notification tap has been reported by the app yet. Release the updated app and "
			"ask a few people to tap a notification — open rates fill in from then on. Until then only "
			"the delivery figures are meaningful.",
		})
	if not sent:
		out.append({
			"title": "Nothing tracked was sent in this period",
			"detail": "Only sends made after tracking shipped carry an id. Send a notification and check "
			"back after people have had time to respond.",
		})
		return out
	if failed and reasons:
		top, n = max(reasons.items(), key=lambda kv: kv[1])
		out.append({
			"title": f"{len(failed)} send{'s' if len(failed) != 1 else ''} failed",
			"detail": f"The most common reason: “{top}” ({n}). Tokens that are no longer valid are removed "
			"automatically; people without a token need to open the app and allow notifications.",
		})
	if accepted and first_event and tapped and len(tapped) / len(accepted) < 0.1:
		out.append({
			"title": "Under 10% of accepted notifications get tapped",
			"detail": "Make the title specific and personal (a verse, a name, a question) instead of "
			"generic, and send closer to the person's reminder hour.",
		})
	if tapped and len(engaged) / len(tapped) < 0.4:
		out.append({
			"title": "Many taps lead nowhere",
			"detail": "Most people who tap don't do anything in the app afterwards. Check the deep link "
			"lands on the right screen (a chapter, not the home page) and that the promise in the title "
			"matches what they see.",
		})
	if segments["repeatedly_ignored"]["users"]:
		n = len(segments["repeatedly_ignored"]["users"])
		out.append({
			"title": f"{n} user{'s' if n != 1 else ''} ignored their last 5 notifications",
			"detail": "Reduce their frequency now — pause reading reminders for a week — rather than keep "
			"sending. Continued unopened sends are the main reason people switch notifications off.",
		})
	if segments["tap_no_action"]["users"]:
		n = len(segments["tap_no_action"]["users"])
		out.append({
			"title": f"{n} user{'s' if n != 1 else ''} tap but never act",
			"detail": "They're interested but the landing isn't paying off. Try a notification that opens "
			"straight to the next chapter they were reading.",
		})
	if segments["responsive"]["users"]:
		n = len(segments["responsive"]["users"])
		out.append({
			"title": f"{n} responsive user{'s' if n != 1 else ''}",
			"detail": "They tap 3 in 10 or more. These are the people to test new notification types on first.",
		})
	return out


@frappe.whitelist(methods=["GET"])
def get_engagement_users(kind, period="7d", limit=200):
	"""kind: a segment key (never_tapped | repeatedly_ignored |
	tap_no_action | responsive | failed) or tapped | ignored."""
	require_admin()
	ctx = _Ctx(period)
	segs = _segments(ctx)

	if kind in segs:
		users = segs[kind]["users"]
	elif kind == "tapped":
		users = list({s.user for s in ctx.sends if s.name in ctx.tapped})
	elif kind == "ignored":
		users = list({s.user for s in ctx.sends if ctx.is_ignored(s)})
	else:
		frappe.throw(frappe._("Unknown kind."), frappe.ValidationError)

	info = {
		u.name: u
		for u in frappe.get_all("User", filters={"name": ["in", users or [""]]}, fields=["name", "full_name", "user_image", "last_active"])
	}
	rows = []
	for user in users:
		mine = [s for s in ctx.sends if s.user == user]
		taps = [s for s in mine if s.name in ctx.tapped]
		u = info.get(user)
		failure = next((s.failure_reason for s in mine if not ctx.accepted(s) and s.failure_reason), None)
		rows.append({
			"user": user,
			"full_name": u.full_name if u and u.full_name else user,
			"user_image": u.user_image if u else None,
			"last_active": str(u.last_active) if u and u.last_active else None,
			"sends": len(mine),
			"taps": len(taps),
			"last_tap": str(max(ctx.tapped[s.name] for s in taps)) if taps else None,
			"reason": failure or "",
		})
	rows.sort(key=lambda r: (-r["sends"], r["full_name"]))
	return {"kind": kind, "period": ctx.period, "total_count": len(rows), "users": rows[: int(limit)]}


def annotate_sends(user: str, sends: list) -> list:
	"""Adds the engagement chain to one user's send-log rows (for the
	per-user timeline): accepted?, received, tapped, and what they did in
	the 30 minutes after tapping."""
	ids = [s["name"] for s in sends if s.get("name")]
	if not ids:
		return sends
	rows = frappe.get_all(
		"TOB User Activity Event",
		filters={"user": user, "event": ["in", ["notification_received", "notification_tapped"]]},
		fields=["event", "event_time", "data"],
		order_by="event_time asc",
	)
	received, tapped = {}, {}
	for r in rows:
		sid = _send_id(r.data)
		if sid:
			(tapped if r.event == "notification_tapped" else received).setdefault(sid, r.event_time)
	acts = frappe.get_all(
		"TOB User Activity Event",
		filters={"user": user, "event": ["not in", list(_NON_ACTION_EVENTS)]},
		fields=["event", "event_time"],
		order_by="event_time asc",
	)
	for s in sends:
		sid = s.get("name")
		tap = tapped.get(sid)
		s["received_at"] = str(received[sid]) if sid in received else None
		s["tapped_at"] = str(tap) if tap else None
		s["actions_after"] = (
			[_ACTION_LABELS.get(a.event, a.event) for a in acts if tap <= a.event_time <= tap + _minutes(ENGAGEMENT_WINDOW_MIN)]
			if tap
			else []
		)
	return sends
