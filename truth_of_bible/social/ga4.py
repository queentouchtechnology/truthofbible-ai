"""Google Analytics 4 (Data API v1beta) — website analytics for the
Social Intelligence Center. Uses the shared Google OAuth connection
(social/google_oauth.py, `analytics.readonly` scope) since GA4 is
private, per-property data — unlike YouTube's public channel-summary
card (social/youtube.py), which uses a plain API key and needs no
consent flow at all.

The property to report on is identified by `ga4_property_id` in
site_config.json — the numeric Property ID from GA4 Admin → Property
Settings (NOT the "G-XXXXXXX" measurement id, which is a different
identifier used for the tracking snippet, not the reporting API).
"""

import frappe
import requests

from truth_of_bible.social import google_oauth

_BASE_URL = "https://analyticsdata.googleapis.com/v1beta"
_TIMEOUT = 15

# A property can have Web + Android + iOS streams together (or just one) —
# filtering to `platform == web` keeps this module honestly reporting web
# traffic only, rather than silently including/mislabeling app traffic as
# "website" when a site has no separate web stream at all (confirmed a
# real scenario: a property that is Android-only would otherwise have its
# app numbers displayed under the "Website (GA4)" card).
_WEB_PLATFORM_FILTER = {
	"filter": {
		"fieldName": "platform",
		"stringFilter": {"value": "web"},
	}
}


def _property_id():
	return frappe.get_site_config().get("ga4_property_id")


def is_configured() -> bool:
	return bool(_property_id()) and google_oauth.is_connected()


def run_report(token: str, property_id: str, body: dict):
	"""Shared by this module and social/app_analytics.py — Firebase
	Analytics for a mobile app IS a GA4 property (a "stream" within one),
	so app analytics queries the exact same Data API, just against a
	different property/filter."""
	response = requests.post(
		f"{_BASE_URL}/properties/{property_id}:runReport",
		json=body,
		headers={"Authorization": f"Bearer {token}"},
		timeout=_TIMEOUT,
	)
	response.raise_for_status()
	return response.json()


def get_website_summary(days: int = 28):
	"""Returns None when GA4 isn't configured, the Google account isn't
	connected, or the call fails — same "None = not connected" convention
	as buffer.list_channels()/youtube.get_channel_summary()."""
	property_id = _property_id()
	if not property_id:
		return None
	token = google_oauth.get_valid_access_token()
	if not token:
		return None

	try:
		data = run_report(
			token,
			property_id,
			{
				"dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
				"metrics": [
					{"name": "activeUsers"},
					{"name": "sessions"},
					{"name": "screenPageViews"},
				],
				"dimensionFilter": _WEB_PLATFORM_FILTER,
			},
		)
	except requests.RequestException:
		return None

	rows = data.get("rows") or []

	def _val(values, i):
		try:
			return int(values[i].get("value") or 0)
		except (IndexError, ValueError, TypeError):
			return 0

	metric_values = rows[0].get("metricValues") if rows else []
	summary = {
		"active_users": _val(metric_values, 0),
		"sessions": _val(metric_values, 1),
		"page_views": _val(metric_values, 2),
		"top_pages": _get_top_pages(token, property_id, days),
	}
	return summary


def _get_top_pages(token: str, property_id: str, days: int, limit: int = 5) -> list:
	try:
		data = run_report(
			token,
			property_id,
			{
				"dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
				"dimensions": [{"name": "pagePath"}],
				"metrics": [{"name": "screenPageViews"}],
				"dimensionFilter": _WEB_PLATFORM_FILTER,
				"orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
				"limit": limit,
			},
		)
	except requests.RequestException:
		return []

	pages = []
	for row in data.get("rows") or []:
		dims = row.get("dimensionValues") or []
		mets = row.get("metricValues") or []
		if not dims or not mets:
			continue
		try:
			views = int(mets[0].get("value") or 0)
		except (ValueError, TypeError):
			views = 0
		pages.append({"path": dims[0].get("value") or "", "views": views})
	return pages
