"""Church Finder — a server-side proxy over Google Places API (New) so the
Maps/Places API key never reaches the client. `google_maps_api_key` lives
only in site_config.json (already live-tested against this project's GCP
account) and is read here, sent only as an outbound request header, and
never echoed back in any response or exception — same discipline as
`communication/chatwoot.py`'s credential handling.

V1 deliberately does not surface Google Photos for results: resolving a
photo reference into a fetchable URL would require echoing the API key in
that URL, which is exactly the client-side exposure this proxy exists to
avoid. Results get a generic icon client-side instead.
"""

import frappe
import requests
from frappe import _

_PLACES_URL = "https://places.googleapis.com/v1/places:searchNearby"
_FIELD_MASK = ",".join(
	[
		"places.id",
		"places.displayName",
		"places.formattedAddress",
		"places.location",
		"places.rating",
		"places.userRatingCount",
		"places.currentOpeningHours.openNow",
	]
)


def _config():
	return frappe.get_site_config().get("google_maps_api_key")


def _log_not_configured():
	frappe.log_error(
		title="Church Finder: Google Maps API key not configured",
		message="site_config.json is missing 'google_maps_api_key'.",
	)


@frappe.whitelist(methods=["POST"])
def search_nearby(lat, lng, radius_m=5000):
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in to use Church Finder."), frappe.PermissionError)

	try:
		lat = float(lat)
		lng = float(lng)
	except (TypeError, ValueError):
		frappe.throw(_("A valid latitude/longitude is required."), frappe.ValidationError)

	try:
		radius_m = float(radius_m)
	except (TypeError, ValueError):
		radius_m = 5000
	radius_m = min(max(radius_m, 500), 50000)  # Places API (New) caps circle radius at 50km

	api_key = _config()
	if not api_key:
		_log_not_configured()
		frappe.throw(_("Church Finder is not configured on this site."), frappe.ValidationError)

	payload = {
		"includedTypes": ["church"],
		"maxResultCount": 20,
		"locationRestriction": {
			"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius_m}
		},
	}
	headers = {
		"Content-Type": "application/json",
		"X-Goog-Api-Key": api_key,
		"X-Goog-FieldMask": _FIELD_MASK,
	}

	try:
		response = requests.post(_PLACES_URL, headers=headers, json=payload, timeout=20)
	except Exception:
		frappe.log_error(title="Church Finder: request failed", message=frappe.get_traceback())
		frappe.throw(_("Could not reach the places service. Try again."), frappe.ValidationError)

	if response.status_code != 200:
		frappe.log_error(
			title="Church Finder: Places API error",
			message=f"HTTP {response.status_code}: {response.text[:2000]}",
		)
		frappe.throw(_("Could not search nearby churches right now."), frappe.ValidationError)

	churches = []
	for place in response.json().get("places", []):
		location = place.get("location") or {}
		opening_hours = place.get("currentOpeningHours") or {}
		churches.append(
			{
				"place_id": place.get("id"),
				"name": (place.get("displayName") or {}).get("text") or "",
				"address": place.get("formattedAddress") or "",
				"latitude": location.get("latitude"),
				"longitude": location.get("longitude"),
				"rating": place.get("rating"),
				"user_rating_count": place.get("userRatingCount"),
				"open_now": opening_hours.get("openNow"),
			}
		)
	return {"churches": churches}
