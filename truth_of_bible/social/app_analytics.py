"""Firebase/App Analytics via the GA4 Data API — Firebase Analytics for a
mobile app IS a GA4 property (each platform is a "stream" within it), so
this reuses the exact same Google OAuth connection and Data API call as
social/ga4.py (`ga4.run_report`), just queried against the app's own
property/data instead of the website's.

Two real-world setups are both supported without needing to know in
advance which one applies:
1. One combined GA4 property with separate Web/Android/iOS streams under
   it — set only `ga4_property_id` (the same key social/ga4.py already
   uses); this module filters by the `platform` dimension (android/ios)
   to isolate app traffic from web traffic within that one property.
2. A dedicated GA4 property was created for the Firebase app — set
   `firebase_ga4_property_id` explicitly in site_config.json. The same
   platform filter is still applied; it's harmless there too, since an
   app-only property's rows are already all android/ios.
"""

import frappe
import requests

from truth_of_bible.social import ga4 as ga4_mod
from truth_of_bible.social import google_oauth

_PLATFORM_FILTER = {
	"filter": {
		"fieldName": "platform",
		"inListFilter": {"values": ["android", "ios"]},
	}
}


def _property_id():
	config = frappe.get_site_config()
	return config.get("firebase_ga4_property_id") or config.get("ga4_property_id")


def is_configured() -> bool:
	return bool(_property_id()) and (
		bool(frappe.get_site_config().get("ga4_service_account")) or google_oauth.is_connected()
	)


def get_app_summary(days: int = 28):
	"""Returns None when not configured/connected or the call fails —
	same "None = not connected" convention as every other source here."""
	property_id = _property_id()
	if not property_id:
		return None
	# Same credential preference as social/ga4.py's own get_access_token()
	# (dedicated GA4 service account first, shared OAuth connection as
	# fallback) — reused directly rather than re-implemented, since this
	# is the exact same Data API/credential as ga4.py, just a different
	# property/filter.
	token = ga4_mod.get_access_token()
	if not token:
		return None

	try:
		data = ga4_mod.run_report(
			token,
			property_id,
			{
				"dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
				"metrics": [
					{"name": "activeUsers"},
					{"name": "newUsers"},
					{"name": "eventCount"},
				],
				"dimensionFilter": _PLATFORM_FILTER,
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
	return {
		"active_users": _val(metric_values, 0),
		"new_users": _val(metric_values, 1),
		"event_count": _val(metric_values, 2),
		"top_events": _get_top_events(token, property_id, days),
	}


def _get_top_events(token: str, property_id: str, days: int, limit: int = 5) -> list:
	try:
		data = ga4_mod.run_report(
			token,
			property_id,
			{
				"dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
				"dimensions": [{"name": "eventName"}],
				"metrics": [{"name": "eventCount"}],
				"dimensionFilter": _PLATFORM_FILTER,
				"orderBys": [{"metric": {"metricName": "eventCount"}, "desc": True}],
				"limit": limit,
			},
		)
	except requests.RequestException:
		return []

	events = []
	for row in data.get("rows") or []:
		dims = row.get("dimensionValues") or []
		mets = row.get("metricValues") or []
		if not dims or not mets:
			continue
		try:
			count = int(mets[0].get("value") or 0)
		except (ValueError, TypeError):
			count = 0
		events.append({"name": dims[0].get("value") or "", "count": count})
	return events
