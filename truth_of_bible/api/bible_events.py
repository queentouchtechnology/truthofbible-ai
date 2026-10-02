"""Bible Events — a curated timeline of Bible events, browsed by every
logged-in user via this module.

`TOB Bible Event` is closed to raw `/api/resource/...` REST for every role
except System Manager — same reasoning as `api/bible_places.py`: this file
is the only door. The content set is small and static (dozens of rows,
admin-curated), so the app fetches it in full and filters/searches
client-side rather than round-tripping per keystroke — `list_events`
intentionally takes no search/filter params.
"""

import frappe


def _event_dict(e) -> dict:
	return {
		"event": e.name,
		"title": e.title,
		"era": e.era,
		"description": e.description or "",
		"relevant_passages": [line.strip() for line in (e.relevant_passages or "").splitlines() if line.strip()],
	}


@frappe.whitelist(methods=["GET"])
def list_events():
	events = frappe.get_all(
		"TOB Bible Event",
		filters={"status": "Published"},
		fields=["name", "title", "era", "description", "relevant_passages"],
		order_by="sort_order asc, title asc",
		ignore_permissions=True,
	)
	return {"events": [_event_dict(e) for e in events]}
