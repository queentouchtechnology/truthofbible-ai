"""Church Finder — a server-side proxy over Google Places API (New) so the
Maps/Places API key never reaches the client. `google_maps_api_key` lives
only in site_config.json (already live-tested against this project's GCP
account) and is read here, sent only as an outbound request header, and
never echoed back in any response or exception — same discipline as
`communication/chatwoot.py`'s credential handling.

**Text Search (New), not Nearby Search** — deliberate: Nearby Search (New)'s
request schema has no `openNow`/`minRating` fields, so it can't back the
"Open now"/"Highly rated" filters at all. Text Search (New) supports both,
plus a free-text `textQuery` — which is also the only way to filter by
denomination ("Catholic church", "Baptist church", ...), since Places has
no denomination attribute to filter on structurally. One endpoint
(`search_churches`) covers "near me" (empty query defaults to "church"),
free-text search, and type filtering — `locationBias` (not
`locationRestriction`, which Text Search only accepts as a rectangle, not a
circle) keeps results anchored near the given point without hard-excluding
a good match just outside the radius.

V1 deliberately does not surface Google Photos for results: resolving a
photo reference into a fetchable URL would require echoing the API key in
that URL, which is exactly the client-side exposure this proxy exists to
avoid. Results get a generic icon client-side instead.
"""

import math

import frappe
import requests
from frappe import _

_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_SEARCH_FIELD_MASK = ",".join(
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

_DETAILS_FIELD_MASK = ",".join(
	[
		"id",
		"displayName",
		"formattedAddress",
		"location",
		"rating",
		"userRatingCount",
		"regularOpeningHours.openNow",
		"regularOpeningHours.weekdayDescriptions",
		"nationalPhoneNumber",
		"internationalPhoneNumber",
		"websiteUri",
		"googleMapsUri",
	]
)

_CHURCH_TYPE_QUERY = {
	"catholic": "Catholic church",
	"orthodox": "Orthodox church",
	"protestant": "Protestant church",
	"baptist": "Baptist church",
	"pentecostal": "Pentecostal church",
	"other": "church",
}


def _config():
	return frappe.get_site_config().get("google_maps_api_key")


def _log_not_configured():
	frappe.log_error(
		title="Church Finder: Google Maps API key not configured",
		message="site_config.json is missing 'google_maps_api_key'.",
	)


def _require_login():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in to use Church Finder."), frappe.PermissionError)


def _require_api_key():
	api_key = _config()
	if not api_key:
		_log_not_configured()
		frappe.throw(_("Church Finder is not configured on this site."), frappe.ValidationError)
	return api_key


def _haversine_m(lat1, lng1, lat2, lng2) -> float:
	"""Great-circle distance in meters. Neither Text Search nor Place
	Details (New) returns a distance field — this is computed here once,
	server-side, so every client shows the same number instead of each
	re-implementing it."""
	r = 6371000
	p1, p2 = math.radians(lat1), math.radians(lat2)
	d_phi = math.radians(lat2 - lat1)
	d_lambda = math.radians(lng2 - lng1)
	a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
	return 2 * r * math.asin(min(1, math.sqrt(a)))


def _build_text_query(query, church_type) -> str:
	query = (query or "").strip()
	type_phrase = _CHURCH_TYPE_QUERY.get((church_type or "").strip().lower())
	if query and type_phrase and type_phrase.lower() not in query.lower():
		return f"{type_phrase} {query}"
	if query:
		return query
	return type_phrase or "church"


@frappe.whitelist(methods=["POST"])
def search_churches(lat, lng, query=None, radius_m=5000, church_type=None, open_now=None, min_rating=None):
	_require_login()

	try:
		lat = float(lat)
		lng = float(lng)
	except (TypeError, ValueError):
		frappe.throw(_("A valid latitude/longitude is required."), frappe.ValidationError)

	try:
		radius_m = float(radius_m)
	except (TypeError, ValueError):
		radius_m = 5000
	radius_m = min(max(radius_m, 500), 50000)  # Text Search (New) caps location bias radius at 50km

	api_key = _require_api_key()

	payload = {
		"textQuery": _build_text_query(query, church_type),
		"includedType": "church",
		"maxResultCount": 20,
		"rankPreference": "DISTANCE",
		"locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius_m}},
	}
	if str(open_now).lower() in ("1", "true", "yes"):
		payload["openNow"] = True
	if min_rating not in (None, "", "0", 0):
		try:
			payload["minRating"] = max(0.0, min(5.0, float(min_rating)))
		except (TypeError, ValueError):
			pass

	headers = {
		"Content-Type": "application/json",
		"X-Goog-Api-Key": api_key,
		"X-Goog-FieldMask": _SEARCH_FIELD_MASK,
	}

	try:
		response = requests.post(_SEARCH_URL, headers=headers, json=payload, timeout=20)
	except Exception:
		frappe.log_error(title="Church Finder: search request failed", message=frappe.get_traceback())
		frappe.throw(_("Could not reach the places service. Try again."), frappe.ValidationError)

	if response.status_code != 200:
		frappe.log_error(
			title="Church Finder: Places API search error",
			message=f"HTTP {response.status_code}: {response.text[:2000]}",
		)
		frappe.throw(_("Could not search churches right now."), frappe.ValidationError)

	churches = []
	for place in response.json().get("places", []):
		location = place.get("location") or {}
		place_lat, place_lng = location.get("latitude"), location.get("longitude")
		opening_hours = place.get("currentOpeningHours") or {}
		churches.append(
			{
				"place_id": place.get("id"),
				"name": (place.get("displayName") or {}).get("text") or "",
				"address": place.get("formattedAddress") or "",
				"latitude": place_lat,
				"longitude": place_lng,
				"rating": place.get("rating"),
				"user_rating_count": place.get("userRatingCount"),
				"open_now": opening_hours.get("openNow"),
				"distance_m": round(_haversine_m(lat, lng, place_lat, place_lng))
				if place_lat is not None and place_lng is not None
				else None,
			}
		)
	churches.sort(key=lambda c: c["distance_m"] if c["distance_m"] is not None else float("inf"))
	return {"churches": churches}


@frappe.whitelist(methods=["GET"])
def get_church_details(place_id):
	_require_login()
	if not place_id:
		frappe.throw(_("A place is required."), frappe.ValidationError)

	api_key = _require_api_key()
	url = f"https://places.googleapis.com/v1/places/{place_id}"
	headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": _DETAILS_FIELD_MASK}

	try:
		response = requests.get(url, headers=headers, timeout=20)
	except Exception:
		frappe.log_error(title="Church Finder: details request failed", message=frappe.get_traceback())
		frappe.throw(_("Could not reach the places service. Try again."), frappe.ValidationError)

	if response.status_code != 200:
		frappe.log_error(
			title="Church Finder: Places API details error",
			message=f"HTTP {response.status_code}: {response.text[:2000]}",
		)
		frappe.throw(_("Could not load this church's details right now."), frappe.ValidationError)

	place = response.json()
	location = place.get("location") or {}
	hours = place.get("regularOpeningHours") or {}
	return {
		"place_id": place.get("id"),
		"name": (place.get("displayName") or {}).get("text") or "",
		"address": place.get("formattedAddress") or "",
		"latitude": location.get("latitude"),
		"longitude": location.get("longitude"),
		"rating": place.get("rating"),
		"user_rating_count": place.get("userRatingCount"),
		"open_now": hours.get("openNow"),
		"weekly_hours": hours.get("weekdayDescriptions") or [],
		"phone": place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber") or "",
		"website": place.get("websiteUri") or "",
		"google_maps_url": place.get("googleMapsUri") or "",
	}
