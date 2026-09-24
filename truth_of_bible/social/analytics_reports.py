"""Detailed GA4 reports for the Social Intelligence screens — the daily
trend, geography/device/channel breakdowns and long top-N lists that the
one-line dashboard summaries (ga4.py / app_analytics.py) can't show.

GA4 is aggregate by design: nothing here is per-user. "Which user did
which event" comes from the separate TOB User Activity Event log
(analytics/activity.py), not from this module.

Results are cached for 10 minutes — GA4 has its own request quotas and
this screen is opened repeatedly by admins.
"""

import frappe
import requests

from truth_of_bible.communication.auth import require_admin
from truth_of_bible.social import app_analytics as app_mod
from truth_of_bible.social import ga4 as ga4_mod

_CACHE_TTL = 600


def _rows(data):
	out = []
	for row in data.get("rows") or []:
		dims = [d.get("value") or "" for d in row.get("dimensionValues") or []]
		mets = []
		for m in row.get("metricValues") or []:
			try:
				mets.append(int(float(m.get("value") or 0)))
			except (TypeError, ValueError):
				mets.append(0)
		out.append((dims, mets))
	return out


def _report(token, property_id, days, platform_filter, dimension, metric, limit=10, order_by_date=False):
	body = {
		"dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
		"dimensions": [{"name": dimension}],
		"metrics": [{"name": metric}],
		"dimensionFilter": platform_filter,
		"limit": limit,
	}
	body["orderBys"] = (
		[{"dimension": {"dimensionName": dimension}}]
		if order_by_date
		else [{"metric": {"metricName": metric}, "desc": True}]
	)
	try:
		return _rows(ga4_mod.run_report(token, property_id, body))
	except requests.RequestException:
		return []


def _buckets(rows):
	return [{"label": dims[0] or "(not set)", "value": mets[0]} for dims, mets in rows if mets]


@frappe.whitelist(methods=["GET"])
def get_analytics_report(kind="app", days=28):
	"""kind: "app" (Firebase/Android+iOS) or "web". Returns `None` when
	GA4 isn't configured for that kind — never fabricated zeros."""
	require_admin()
	kind = "web" if kind == "web" else "app"
	days = max(1, min(int(days), 90))

	cache_key = f"tob_ga4_report_{kind}_{days}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached

	if kind == "web":
		property_id, platform_filter = ga4_mod._property_id(), ga4_mod._WEB_PLATFORM_FILTER
	else:
		property_id, platform_filter = app_mod._property_id(), app_mod._PLATFORM_FILTER
	token = ga4_mod.get_access_token()
	if not property_id or not token:
		return None

	trend_metric = "screenPageViews" if kind == "web" else "eventCount"
	trend = [
		{"date": dims[0], "value": mets[0]}
		for dims, mets in _report(
			token, property_id, days, platform_filter, "date", trend_metric, limit=days + 1, order_by_date=True
		)
		if mets
	]

	breakdowns = [
		{"title": "Countries", "rows": _buckets(_report(token, property_id, days, platform_filter, "country", "activeUsers"))},
		{"title": "Devices", "rows": _buckets(_report(token, property_id, days, platform_filter, "deviceCategory", "activeUsers"))},
	]
	if kind == "web":
		breakdowns.append({
			"title": "Traffic sources",
			"rows": _buckets(_report(token, property_id, days, platform_filter, "sessionDefaultChannelGroup", "sessions")),
		})
		top_title = "Top pages"
		top_rows = _buckets(_report(token, property_id, days, platform_filter, "pagePath", "screenPageViews", limit=20))
	else:
		breakdowns.append({
			"title": "App versions",
			"rows": _buckets(_report(token, property_id, days, platform_filter, "appVersion", "activeUsers")),
		})
		top_title = "Top events"
		top_rows = _buckets(_report(token, property_id, days, platform_filter, "eventName", "eventCount", limit=25))

	result = {
		"kind": kind,
		"days": days,
		"trend_label": "Page views per day" if kind == "web" else "Events per day",
		"trend": trend,
		"breakdowns": [b for b in breakdowns if b["rows"]],
		"top_title": top_title,
		"top": top_rows,
	}
	frappe.cache().set_value(cache_key, result, expires_in_sec=_CACHE_TTL)
	return result
