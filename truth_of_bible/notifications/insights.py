"""Admin insights for the notification log: what was sent in a period, who
received what, who didn't (and why), who is using the app regularly, and
who can't be reached by push at all — plus rule-based suggestions.

Two honest limits, both surfaced in the UI rather than hidden:

- The engine only records SENDS (TOB Notification Send Log). A skipped
  send (preference off, quiet hours, daily cap, already sent) leaves no
  row, so a "reason" here is derived from each user's CURRENT state —
  their token, preferences and reading state — not replayed from a
  history that doesn't exist.
- Activity comes from the core `User.last_active` field, which Frappe
  updates on session activity. A user whose app session hasn't touched
  the server recently shows as inactive even if they open the app offline
  (the Bible reader works offline).
"""

import frappe
from frappe.utils import add_days, get_datetime, getdate, now_datetime, nowdate

from truth_of_bible.communication.auth import require_admin

_PERIODS = ("today", "yesterday", "7d", "30d", "90d")

_SEGMENT_LABELS = {
	"regular": "Regular (active in the last 7 days)",
	"occasional": "Occasional (8–30 days ago)",
	"inactive": "Inactive (over 30 days)",
	"never": "No recorded activity",
}

_REASONS = {
	"no_token": "No push token — notifications were never allowed in the app, or they logged out",
	"pref_off": "Turned off Bible reading and spiritual growth notifications",
	"no_reading": "Hasn't read in the app yet, so no reading reminders are scheduled",
	"read_today": "Read today — reading reminders skip anyone who already read",
	"nothing_sent": "Eligible, but nothing was sent in this period — their reminder hour may fall in quiet hours",
	"received": "",
}


def _range(period: str):
	today = get_datetime(nowdate())
	if period == "today":
		return today, add_days(today, 1)
	if period == "yesterday":
		return add_days(today, -1), today
	days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 7)
	return add_days(today, -(days - 1)), add_days(today, 1)


def _segment(last_active, now) -> str:
	if not last_active:
		return "never"
	days = (now - get_datetime(last_active)).days
	if days <= 7:
		return "regular"
	if days <= 30:
		return "occasional"
	return "inactive"


class _Context:
	"""Everything both endpoints need, loaded once per request."""

	def __init__(self, period: str):
		self.period = period if period in _PERIODS else "7d"
		self.start, self.end = _range(self.period)
		self.now = now_datetime()
		self.today = getdate(nowdate())

		self.users = {
			r.name: r
			for r in frappe.get_all(
				"User",
				filters={"enabled": 1, "name": ["not in", ["Guest", "Administrator"]]},
				fields=["name", "full_name", "user_image", "last_active"],
			)
		}
		self.token_users = set(frappe.get_all("User FCM Token", pluck="user"))
		self.prefs = {
			r.user: r
			for r in frappe.get_all(
				"TOB Notification Preference",
				fields=["user", "bible_reading", "spiritual_growth"],
			)
		}
		self.reading = {
			r.user: r
			for r in frappe.get_all(
				"TOB User Reading State", fields=["user", "last_read_at", "last_read_date"]
			)
		}

		sent = frappe.db.sql(
			"""
			select user, count(*) as c, max(sent_at) as last_sent,
				group_concat(distinct event_code) as events
			from `tabTOB Notification Send Log`
			where sent_at >= %(s)s and sent_at < %(e)s
			group by user
			""",
			{"s": self.start, "e": self.end},
			as_dict=True,
		)
		self.received = {r.user: r for r in sent}
		self.ever_received = set(
			frappe.db.sql_list("select distinct user from `tabTOB Notification Send Log`")
		)

	def reason(self, user: str):
		"""(key, text) for why this user got nothing in the period."""
		if user in self.received:
			return "received", ""
		if user not in self.token_users:
			return "no_token", _REASONS["no_token"]
		pref = self.prefs.get(user)
		if pref and not pref.bible_reading and not pref.spiritual_growth:
			return "pref_off", _REASONS["pref_off"]
		rs = self.reading.get(user)
		if not rs or not rs.last_read_at:
			return "no_reading", _REASONS["no_reading"]
		if rs.last_read_date == self.today:
			return "read_today", _REASONS["read_today"]
		return "nothing_sent", _REASONS["nothing_sent"]

	def row(self, user: str) -> dict:
		u = self.users.get(user)
		got = self.received.get(user)
		key, text = self.reason(user)
		return {
			"user": user,
			"full_name": (u.full_name if u and u.full_name else user),
			"user_image": u.user_image if u else None,
			"last_active": str(u.last_active) if u and u.last_active else None,
			"segment": _segment(u.last_active if u else None, self.now),
			"has_token": user in self.token_users,
			"received_count": int(got.c) if got else 0,
			"last_sent": str(got.last_sent) if got else None,
			"events": (got.events or "").split(",") if got else [],
			"reason_key": key,
			"reason": text,
		}


@frappe.whitelist(methods=["GET"])
def get_notification_summary(period="7d"):
	require_admin()
	ctx = _Context(period)

	titles = {
		t.name: t.title
		for t in frappe.get_all("TOB Notification Template", fields=["name", "title"])
	}
	by_event = frappe.db.sql(
		"""
		select event_code as event, count(*) as count, count(distinct user) as users
		from `tabTOB Notification Send Log`
		where sent_at >= %(s)s and sent_at < %(e)s
		group by event_code order by count desc
		""",
		{"s": ctx.start, "e": ctx.end},
		as_dict=True,
	)
	for e in by_event:
		e["title"] = titles.get(e["event"]) or e["event"]

	by_day = []
	if ctx.period in ("7d", "30d", "90d"):
		by_day = frappe.db.sql(
			"""
			select date(sent_at) as date, count(*) as count
			from `tabTOB Notification Send Log`
			where sent_at >= %(s)s and sent_at < %(e)s
			group by date(sent_at) order by date(sent_at)
			""",
			{"s": ctx.start, "e": ctx.end},
			as_dict=True,
		)
		for d in by_day:
			d["date"] = str(d["date"])

	sent_total = sum(int(r.c) for r in ctx.received.values())
	recipients = len(ctx.received)

	# Audience: every enabled user, split by activity and by reachability.
	segments = {k: {"total": 0, "with_token": 0, "received": 0} for k in _SEGMENT_LABELS}
	reasons = {}
	never_received_with_token = 0
	for user in ctx.users:
		seg = segments[_segment(ctx.users[user].last_active, ctx.now)]
		seg["total"] += 1
		has_token = user in ctx.token_users
		if has_token:
			seg["with_token"] += 1
		if user in ctx.received:
			seg["received"] += 1
		key, _text = ctx.reason(user)
		if key != "received":
			reasons[key] = reasons.get(key, 0) + 1
		if has_token and user not in ctx.ever_received:
			never_received_with_token += 1

	with_token = sum(1 for u in ctx.users if u in ctx.token_users)
	total_users = len(ctx.users)
	audience = {
		"total_users": total_users,
		"with_token": with_token,
		"without_token": total_users - with_token,
		"received": recipients,
		"not_received_with_token": max(
			0, sum(1 for u in ctx.token_users if u in ctx.users and u not in ctx.received)
		),
		"never_received_ever": never_received_with_token,
	}

	return {
		"period": ctx.period,
		"range": {"start": str(ctx.start.date()), "end": str(add_days(ctx.end, -1).date())},
		"sent_total": sent_total,
		"recipients": recipients,
		"avg_per_recipient": round(sent_total / recipients, 1) if recipients else 0,
		"by_event": by_event,
		"by_day": by_day,
		"audience": audience,
		"segments": [
			{"key": k, "label": _SEGMENT_LABELS[k], **v} for k, v in segments.items()
		],
		"skip_reasons": [
			{"key": k, "reason": _REASONS[k], "count": c}
			for k, c in sorted(reasons.items(), key=lambda kv: -kv[1])
		],
		"suggestions": _suggestions(ctx, audience, segments, reasons, sent_total, recipients),
		"note": (
			"Skips aren't logged by the engine, so each reason reflects the user's "
			"current state (token, preferences, reading state), not a replay of the past."
		),
	}


def _suggestions(ctx, audience, segments, reasons, sent_total, recipients):
	out = []
	reg = segments["regular"]
	if reg["total"] and reg["with_token"] < reg["total"]:
		gap = reg["total"] - reg["with_token"]
		out.append({
			"title": f"{gap} regular user{'s' if gap != 1 else ''} can't receive push",
			"detail": "They open the app every week but never allowed notifications. This is the "
			"highest-value gap: ask for permission right after a satisfying moment (finishing a "
			"chapter or a quiz), with one line on what they'll get — not on first launch. "
			"Reach them now through the Communication Center by email or WhatsApp.",
		})
	inactive = segments["inactive"]
	if inactive["with_token"]:
		out.append({
			"title": f"{inactive['with_token']} inactive user{'s' if inactive['with_token'] != 1 else ''} still have push",
			"detail": "Send one gentle win-back message, not a stream: a single verse or a "
			"'we've saved your place' note. Cap it at one every 7–10 days and stop after two "
			"unopened ones. Never imply guilt about being away.",
		})
	no_token_inactive = inactive["total"] - inactive["with_token"]
	if no_token_inactive > 0:
		out.append({
			"title": f"{no_token_inactive} inactive user{'s' if no_token_inactive != 1 else ''} can't be reached by push",
			"detail": "Push isn't an option for them. Use an email or WhatsApp campaign from the "
			"Communication Center for a one-time re-introduction.",
		})
	never = segments["never"]
	if never["total"]:
		out.append({
			"title": f"{never['total']} user{'s' if never['total'] != 1 else ''} have no recorded activity",
			"detail": "Signed up but never used the app (or use it only offline). A short welcome "
			"series that points to one first action — read today's verse — works better than a "
			"generic announcement.",
		})
	if reasons.get("pref_off"):
		out.append({
			"title": f"{reasons['pref_off']} user{'s' if reasons['pref_off'] != 1 else ''} turned reading notifications off",
			"detail": "Respect it — don't override their setting. If it's a large number, review "
			"whether reminders arrive at a bad hour; offer a quieter schedule instead of a mute.",
		})
	if audience["never_received_ever"]:
		out.append({
			"title": f"{audience['never_received_ever']} user{'s' if audience['never_received_ever'] != 1 else ''} with push have never received anything",
			"detail": "Registered and able to receive, but no notification has ever matched them. "
			"A one-time welcome or 'today's verse' broadcast is a safe way to start.",
		})
	if recipients and sent_total / recipients > 4 and ctx.period in ("today", "yesterday"):
		out.append({
			"title": "High send volume per person",
			"detail": "Recipients averaged over 4 notifications in a single day. Fatigue is the "
			"main reason people switch push off — consider lowering the daily cap.",
		})
	if not sent_total:
		out.append({
			"title": "Nothing was sent in this period",
			"detail": "Check the Templates tab (is the template enabled?) and the Errors tab for "
			"delivery failures.",
		})
	return out


@frappe.whitelist(methods=["GET"])
def get_insight_users(kind, period="7d", limit=100, offset=0, search=None):
	"""kind: received | not_received | no_token | never_received |
	regular | occasional | inactive | never."""
	require_admin()
	ctx = _Context(period)

	if kind == "received":
		users = list(ctx.received.keys())
	elif kind == "not_received":
		users = [u for u in ctx.token_users if u in ctx.users and u not in ctx.received]
	elif kind == "no_token":
		users = [u for u in ctx.users if u not in ctx.token_users]
	elif kind == "never_received":
		users = [u for u in ctx.token_users if u in ctx.users and u not in ctx.ever_received]
	elif kind in _SEGMENT_LABELS:
		users = [u for u in ctx.users if _segment(ctx.users[u].last_active, ctx.now) == kind]
	else:
		frappe.throw(frappe._("Unknown kind."), frappe.ValidationError)

	rows = [ctx.row(u) for u in users if u in ctx.users]
	if search:
		needle = search.strip().lower()
		rows = [r for r in rows if needle in r["full_name"].lower() or needle in r["user"].lower()]

	if kind == "received":
		rows.sort(key=lambda r: -r["received_count"])
	else:
		rows.sort(key=lambda r: r["last_active"] or "", reverse=True)

	total = len(rows)
	start = int(offset)
	return {
		"kind": kind,
		"period": ctx.period,
		"total_count": total,
		"users": rows[start : start + int(limit)],
	}


@frappe.whitelist(methods=["GET"])
def get_user_notification_history(user, limit=100):
	"""One user's full notification picture for the admin drill-down:
	who they are and whether they can receive push, their preferences,
	every send recorded for them, the in-app notifications they were
	given (with read state), and any delivery errors mentioning them."""
	require_admin()
	limit = min(int(limit), 300)

	ctx = _Context("30d")
	base = ctx.row(user)
	base["devices"] = frappe.db.count("User FCM Token", {"user": user})

	pref = frappe.db.get_value(
		"TOB Notification Preference",
		{"user": user},
		[
			"bible_reading", "spiritual_growth", "bible_study", "prayer", "quiz",
			"courses", "community", "shopping", "account", "announcements",
			"daily_reminder_time", "quiet_hours_start", "quiet_hours_end",
			"max_daily_notifications", "timezone",
		],
		as_dict=True,
	)
	if pref:
		for k in ("daily_reminder_time", "quiet_hours_start", "quiet_hours_end"):
			pref[k] = str(pref[k]) if pref.get(k) is not None else None

	titles = {
		t.name: t.title
		for t in frappe.get_all("TOB Notification Template", fields=["name", "title"])
	}
	sends = frappe.get_all(
		"TOB Notification Send Log",
		filters={"user": user},
		fields=[
			"name", "event_code", "sent_at", "tracked",
			"devices_reached", "devices_failed", "failure_reason",
		],
		order_by="sent_at desc",
		limit_page_length=limit,
	)
	from truth_of_bible.notifications.engagement import annotate_sends

	annotate_sends(user, sends)
	for s in sends:
		s["title"] = titles.get(s["event_code"]) or s["event_code"]
		s["sent_at"] = str(s["sent_at"])

	inapp = frappe.get_all(
		"Notification Log",
		filters={"for_user": user},
		fields=["subject", "creation", "read"],
		order_by="creation desc",
		limit_page_length=limit,
	)
	for n in inapp:
		n["creation"] = str(n["creation"])

	errors = frappe.get_all(
		"Error Log",
		filters={"method": ["like", "Notification engine%"], "error": ["like", f"%{user}%"]},
		fields=["name", "method", "creation"],
		order_by="creation desc",
		limit_page_length=50,
	)
	for e in errors:
		e["creation"] = str(e["creation"])

	return {
		"profile": base,
		"preferences": pref,
		"total_sends": frappe.db.count("TOB Notification Send Log", {"user": user}),
		"sends": sends,
		"in_app": inapp,
		"errors": errors,
	}
