"""Bible Places — a curated map of biblical places, grouped into guided
journeys (e.g. "Paul's Missionary Journeys"), browsed by every logged-in
user via this module.

`TOB Bible Place`, `TOB Bible Journey`, and `TOB Bible Journey Stop` are all
closed to raw `/api/resource/...` REST for every role except System Manager
— same reasoning as `api/reading_plan.py`: this file is the only door. The
content set is small and static (dozens of rows, admin-curated), so the app
fetches it in full and filters/searches client-side rather than round-
tripping per keystroke — `list_places`/`list_journeys` intentionally take no
search/filter params.
"""

import frappe
from frappe import _


def _place_dict(p) -> dict:
	return {
		"place": p.name,
		"title": p.title,
		"category": p.category,
		"region": p.region or "",
		"latitude": p.latitude,
		"longitude": p.longitude,
		"primary_verse_ref": p.primary_verse_ref or "",
		"description": p.description or "",
		"facts": [line.strip() for line in (p.facts or "").splitlines() if line.strip()],
		"photo_url": p.photo_url or "",
		# Falls back to `primary_verse_ref` alone client-side when this is
		# empty — most existing rows predate this field.
		"relevant_passages": [line.strip() for line in (p.relevant_passages or "").splitlines() if line.strip()],
	}


def _journey_dict(j) -> dict:
	return {
		"journey": j.name,
		"title": j.title,
		"description": j.description or "",
		"icon": j.icon,
		"accent_color": j.accent_color,
	}


@frappe.whitelist(methods=["GET"])
def list_places():
	places = frappe.get_all(
		"TOB Bible Place",
		filters={"status": "Published"},
		fields=[
			"name", "title", "category", "region", "latitude", "longitude",
			"primary_verse_ref", "description", "facts", "photo_url", "relevant_passages",
		],
		order_by="region asc, sort_order asc, title asc",
		ignore_permissions=True,
	)
	return {"places": [_place_dict(p) for p in places]}


@frappe.whitelist(methods=["GET"])
def get_place(place):
	p = frappe.get_doc("TOB Bible Place", place)
	if p.status != "Published" and "System Manager" not in frappe.get_roles():
		frappe.throw(_("This place isn't available."), frappe.PermissionError)

	stop_journeys = frappe.get_all(
		"TOB Bible Journey Stop", filters={"place": place}, fields=["journey"], ignore_permissions=True
	)
	journey_names = list({r.journey for r in stop_journeys})
	journeys = []
	if journey_names:
		journey_docs = frappe.get_all(
			"TOB Bible Journey",
			filters={"name": ["in", journey_names], "status": "Published"},
			fields=["name", "title", "icon", "accent_color"],
			order_by="sort_order asc, title asc",
			ignore_permissions=True,
		)
		journeys = [
			{"journey": j.name, "title": j.title, "icon": j.icon, "accent_color": j.accent_color}
			for j in journey_docs
		]

	result = _place_dict(p)
	result["journeys"] = journeys
	return result


@frappe.whitelist(methods=["GET"])
def list_journeys():
	journeys = frappe.get_all(
		"TOB Bible Journey",
		filters={"status": "Published"},
		fields=["name", "title", "description", "icon", "accent_color", "sort_order"],
		order_by="sort_order asc, title asc",
		ignore_permissions=True,
	)
	if not journeys:
		return {"journeys": []}

	journey_names = [j.name for j in journeys]
	stop_counts = frappe.get_all(
		"TOB Bible Journey Stop",
		filters={"journey": ["in", journey_names]},
		fields=["journey", "count(name) as stop_count"],
		group_by="journey",
		ignore_permissions=True,
	)
	stop_count_by_journey = {r.journey: r.stop_count for r in stop_counts}

	rows = []
	for j in journeys:
		row = _journey_dict(j)
		row["stop_count"] = stop_count_by_journey.get(j.name, 0)
		rows.append(row)
	return {"journeys": rows}


@frappe.whitelist(methods=["GET"])
def get_journey(journey):
	j = frappe.get_doc("TOB Bible Journey", journey)
	if j.status != "Published" and "System Manager" not in frappe.get_roles():
		frappe.throw(_("This journey isn't available."), frappe.PermissionError)

	stops = frappe.get_all(
		"TOB Bible Journey Stop",
		filters={"journey": journey},
		fields=["stop_number", "place", "note"],
		order_by="stop_number asc",
		ignore_permissions=True,
	)
	place_names = [s.place for s in stops]
	places_by_name = {}
	if place_names:
		place_docs = frappe.get_all(
			"TOB Bible Place",
			filters={"name": ["in", place_names]},
			fields=["name", "title", "category", "region", "latitude", "longitude", "photo_url", "primary_verse_ref"],
			ignore_permissions=True,
		)
		places_by_name = {p.name: p for p in place_docs}

	stop_rows = []
	for s in stops:
		place = places_by_name.get(s.place)
		if not place:
			continue
		stop_rows.append(
			{
				"stop_number": s.stop_number,
				"note": s.note or "",
				"place": place.name,
				"title": place.title,
				"category": place.category,
				"region": place.region or "",
				"latitude": place.latitude,
				"longitude": place.longitude,
				"photo_url": place.photo_url or "",
				"primary_verse_ref": place.primary_verse_ref or "",
			}
		)

	result = _journey_dict(j)
	result["stops"] = stop_rows
	return result
