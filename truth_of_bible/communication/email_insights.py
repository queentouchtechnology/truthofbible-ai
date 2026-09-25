"""Admin email insights, straight from Brevo's own statistics API — how
many emails were sent/delivered/opened/clicked/bounced/unsubscribed per
period, who received them, who is actually reading, who unsubscribed —
plus a per-campaign breakdown from our own recipient table.

Why Brevo and not only our database: TOB Communication Campaign Recipient
keeps just the LATEST status per recipient (no history, no timestamps per
event), so "how many were opened yesterday" or "who unsubscribed this
week" can't be answered from it. Brevo's event log can.

Only mail sent through Brevo's transactional API (what the Communication
Center uses) is covered. Every Brevo call is cached for 10 minutes — the
account has request limits, and this screen gets opened repeatedly.
The API key is read from site_config.json and never returned or logged.
"""

import frappe
import requests
from frappe.utils import add_days, get_datetime, nowdate

from truth_of_bible.communication.auth import require_admin

_BASE = "https://api.brevo.com/v3/smtp/statistics"
_TIMEOUT = 20
_CACHE_TTL = 600
_PERIODS = ("today", "yesterday", "7d", "30d", "90d")
_MAX_EVENT_PAGES = 5  # 5 x 100 = up to 500 events per list

# Our list "kind" -> the Brevo event name(s) behind it.
_KIND_EVENTS = {
	"received": ["delivered"],
	"opened": ["opened"],
	"clicked": ["clicks"],
	"unsubscribed": ["unsubscribed"],
	"bounced": ["hardBounces", "softBounces", "blocked", "invalid"],
}


def _api_key():
	return frappe.get_site_config().get("brevo_api_key")


def _dates(period: str):
	today = get_datetime(nowdate()).date()
	if period == "today":
		return today, today
	if period == "yesterday":
		y = add_days(today, -1)
		return y, y
	days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 7)
	return add_days(today, -(days - 1)), today


def _get(path: str, params: dict):
	"""One cached GET against Brevo. Raises requests.RequestException."""
	cache_key = "tob_brevo_" + path + "_" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached
	response = requests.get(
		f"{_BASE}/{path}",
		params=params,
		headers={"api-key": _api_key(), "Accept": "application/json"},
		timeout=_TIMEOUT,
	)
	response.raise_for_status()
	data = response.json()
	frappe.cache().set_value(cache_key, data, expires_in_sec=_CACHE_TTL)
	return data


def _friendly_error(e: Exception) -> str:
	status = getattr(getattr(e, "response", None), "status_code", None)
	if status == 401:
		return "Brevo rejected the API key (401) — check 'brevo_api_key' in site_config.json."
	if status == 429:
		return "Brevo's rate limit was reached — try again in a few minutes."
	return "Couldn't reach Brevo's statistics API right now."


def _pct(part, whole):
	return round(100 * part / whole, 1) if whole else 0


@frappe.whitelist(methods=["GET"])
def get_email_summary(period="7d"):
	require_admin()
	period = period if period in _PERIODS else "7d"
	if not _api_key():
		return {"configured": False, "period": period}

	start, end = _dates(period)
	dates = {"startDate": str(start), "endDate": str(end)}
	try:
		agg = _get("aggregatedReport", dates)
		daily = []
		if period in ("7d", "30d", "90d"):
			daily = _get("reports", {**dates, "limit": 100, "sort": "asc"}).get("reports") or []
	except requests.RequestException as e:
		return {"configured": True, "period": period, "error": _friendly_error(e)}

	requests_n = int(agg.get("requests") or 0)
	delivered = int(agg.get("delivered") or 0)
	opens = int(agg.get("uniqueOpens") or 0)
	clicks = int(agg.get("uniqueClicks") or 0)
	bounces = int(agg.get("hardBounces") or 0) + int(agg.get("softBounces") or 0)
	blocked = int(agg.get("blocked") or 0) + int(agg.get("invalid") or 0)
	unsub = int(agg.get("unsubscribed") or 0)
	spam = int(agg.get("spamReports") or 0)

	totals = {
		"sent": requests_n,
		"delivered": delivered,
		"opened": opens,
		"clicked": clicks,
		"bounced": bounces,
		"blocked": blocked,
		"unsubscribed": unsub,
		"spam": spam,
		"delivery_rate": _pct(delivered, requests_n),
		"open_rate": _pct(opens, delivered),
		"click_rate": _pct(clicks, delivered),
		"unsubscribe_rate": _pct(unsub, delivered),
	}

	return {
		"configured": True,
		"period": period,
		"range": {"start": str(start), "end": str(end)},
		"totals": totals,
		"daily": [
			{
				"date": d.get("date"),
				"sent": int(d.get("requests") or 0),
				"delivered": int(d.get("delivered") or 0),
				"opened": int(d.get("uniqueOpens") or 0),
				"unsubscribed": int(d.get("unsubscribed") or 0),
			}
			for d in daily
		],
		"campaigns": _campaign_breakdown(start, end),
		"opted_out_users": frappe.db.count(
			"TOB Notification Preference", {"communication_center_email_opt_out": 1}
		),
		"suggestions": _suggestions(totals),
		"note": (
			"Figures come from Brevo for mail sent through the Communication Center. Opens are "
			"unique opens; some mail apps pre-load images, so open counts run a little high and "
			"clicks are the more reliable sign of real reading."
		),
	}


def _campaign_breakdown(start, end):
	rows = frappe.db.sql(
		"""
		select c.name as campaign, c.campaign_name as name,
			count(*) as recipients,
			sum(r.email_status in ('DELIVERED', 'OPENED', 'CLICKED')) as delivered,
			sum(r.email_status in ('OPENED', 'CLICKED')) as opened,
			sum(r.email_status = 'CLICKED') as clicked,
			sum(r.email_status in ('BOUNCED', 'FAILED')) as failed
		from `tabTOB Communication Campaign Recipient` r
		join `tabTOB Communication Campaign` c on c.name = r.campaign
		where r.email_status not in ('NOT_APPLICABLE') and date(r.creation) between %(s)s and %(e)s
		group by c.name, c.campaign_name
		order by recipients desc
		limit 20
		""",
		{"s": start, "e": end},
		as_dict=True,
	)
	return [
		{
			"campaign": r.campaign,
			"name": r.name or r.campaign,
			"recipients": int(r.recipients or 0),
			"delivered": int(r.delivered or 0),
			"opened": int(r.opened or 0),
			"clicked": int(r.clicked or 0),
			"failed": int(r.failed or 0),
		}
		for r in rows
	]


def _suggestions(t):
	out = []
	if not t["sent"]:
		out.append({
			"title": "No email was sent in this period",
			"detail": "Nothing to analyse yet. Send a campaign from the Communication Center with "
			"the Email channel on to start collecting numbers.",
		})
		return out
	if t["delivery_rate"] and t["delivery_rate"] < 95:
		out.append({
			"title": f"Delivery rate is {t['delivery_rate']}%",
			"detail": "Below 95% means addresses are bouncing or being blocked. Check the Bounced "
			"list, remove addresses that hard-bounced, and confirm the sender domain is verified "
			"in Brevo.",
		})
	if t["delivered"] and t["open_rate"] < 20:
		out.append({
			"title": f"Open rate is {t['open_rate']}%",
			"detail": "Low opens usually mean the subject line isn't landing or the send time is "
			"off. Try a shorter, personal subject (a verse or a question) and send when people "
			"are usually reading — early morning or evening.",
		})
	if t["delivered"] and t["opened"] and t["click_rate"] < 2:
		out.append({
			"title": "Few people click through",
			"detail": "People open but don't act. Put one clear button or link near the top and "
			"make each email about a single thing.",
		})
	if t["unsubscribe_rate"] >= 0.5:
		out.append({
			"title": f"{t['unsubscribed']} unsubscribe{'s' if t['unsubscribed'] != 1 else ''} ({t['unsubscribe_rate']}%)",
			"detail": "Above about 0.5% is a warning sign. Send less often, keep the tone gentle "
			"and relevant, and look at which campaign caused it before the next send.",
		})
	if t["spam"]:
		out.append({
			"title": f"{t['spam']} spam report{'s' if t['spam'] != 1 else ''}",
			"detail": "Spam reports hurt deliverability for everyone. Make sure only people who "
			"expect the mail receive it, and that the unsubscribe link is easy to find.",
		})
	if not out:
		out.append({
			"title": "Email is healthy",
			"detail": "Delivery, opens and unsubscribes are all within normal ranges. Keep the "
			"cadence steady rather than increasing it.",
		})
	return out


def _user_map(emails):
	"""email -> {user, full_name, user_image} for emails that are users."""
	if not emails:
		return {}
	rows = frappe.get_all(
		"User",
		filters={"name": ["in", list(emails)]},
		fields=["name", "full_name", "user_image"],
	)
	return {r.name: r for r in rows}


def _events(kind: str, period: str):
	start, end = _dates(period)
	out = []
	for event in _KIND_EVENTS[kind]:
		for page in range(_MAX_EVENT_PAGES):
			data = _get(
				"events",
				{
					"startDate": str(start),
					"endDate": str(end),
					"event": event,
					"limit": 100,
					"offset": page * 100,
					"sort": "desc",
				},
			)
			batch = data.get("events") or []
			out.extend(batch)
			if len(batch) < 100:
				break
	return out


@frappe.whitelist(methods=["GET"])
def get_email_people(kind, period="7d", search=None):
	"""kind: received | opened | clicked | unsubscribed | bounced. Returns
	one row per email address with how often it appeared, when last, and
	which subjects — capped at 500 events per list."""
	require_admin()
	if kind not in _KIND_EVENTS:
		frappe.throw(frappe._("Unknown kind."), frappe.ValidationError)
	period = period if period in _PERIODS else "7d"
	if not _api_key():
		return {"configured": False, "people": [], "total_count": 0}

	try:
		events = _events(kind, period)
	except requests.RequestException as e:
		return {"configured": True, "error": _friendly_error(e), "people": [], "total_count": 0}

	grouped = {}
	for ev in events:
		email = (ev.get("email") or "").lower()
		if not email:
			continue
		g = grouped.setdefault(
			email, {"email": email, "count": 0, "last_at": ev.get("date"), "subjects": [], "reason": ev.get("reason")}
		)
		g["count"] += 1
		subject = ev.get("subject")
		if subject and subject not in g["subjects"] and len(g["subjects"]) < 3:
			g["subjects"].append(subject)
		if ev.get("reason") and not g["reason"]:
			g["reason"] = ev.get("reason")

	# Everyone who opted out locally is an unsubscriber too — the webhook
	# flips this flag, and Brevo's event window may not cover an older one.
	local_optout = {
		r.user: r
		for r in frappe.get_all(
			"TOB Notification Preference",
			filters={"communication_center_email_opt_out": 1},
			fields=["user", "modified"],
		)
	}
	if kind == "unsubscribed":
		for user, row in local_optout.items():
			g = grouped.setdefault(
				user.lower(),
				{"email": user.lower(), "count": 0, "last_at": str(row.modified), "subjects": [], "reason": "Opted out in the app"},
			)
			g.setdefault("source", "app")

	users = _user_map(set(grouped.keys()) | set(u.lower() for u in local_optout))
	people = []
	for email, g in grouped.items():
		u = users.get(email)
		people.append({
			**g,
			"user": u.name if u else None,
			"full_name": (u.full_name if u and u.full_name else email),
			"user_image": u.user_image if u else None,
			"opted_out": any(k.lower() == email for k in local_optout),
		})
	if search:
		needle = search.strip().lower()
		people = [p for p in people if needle in p["full_name"].lower() or needle in p["email"]]
	people.sort(key=lambda p: (p["count"], p["last_at"] or ""), reverse=True)
	return {"configured": True, "kind": kind, "period": period, "total_count": len(people), "people": people[:300]}


@frappe.whitelist(methods=["GET"])
def get_user_email_history(user, days=90):
	"""One person's mail history from Brevo — every event (sent, delivered,
	opened, clicked, bounced, unsubscribed) for their address, newest first."""
	require_admin()
	if not _api_key():
		return {"configured": False, "events": []}
	try:
		data = _get("events", {"email": user, "days": min(int(days), 90), "limit": 100, "sort": "desc"})
	except requests.RequestException as e:
		return {"configured": True, "error": _friendly_error(e), "events": []}
	return {
		"configured": True,
		"opted_out": bool(
			frappe.db.get_value(
				"TOB Notification Preference", {"user": user}, "communication_center_email_opt_out"
			)
		),
		"events": [
			{
				"event": e.get("event"),
				"date": e.get("date"),
				"subject": e.get("subject"),
				"reason": e.get("reason"),
				"link": e.get("link"),
			}
			for e in (data.get("events") or [])
		],
	}
