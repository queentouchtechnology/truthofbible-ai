"""Bible Characters — a curated set of Bible people, browsed by every
logged-in user via this module.

`TOB Bible Character` is closed to raw `/api/resource/...` REST for every
role except System Manager — same reasoning as `api/bible_places.py`: this
file is the only door. The content set is small and static (dozens of
rows, admin-curated), so the app fetches it in full and filters/searches
client-side rather than round-tripping per keystroke — `list_characters`
intentionally takes no search/filter params.
"""

import frappe


def _character_dict(c) -> dict:
	return {
		"character": c.name,
		"title": c.title,
		"testament": c.testament,
		"role": c.role or "",
		"relevant_passages": [line.strip() for line in (c.relevant_passages or "").splitlines() if line.strip()],
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def list_characters():
	characters = frappe.get_all(
		"TOB Bible Character",
		filters={"status": "Published"},
		fields=["name", "title", "testament", "role", "relevant_passages"],
		order_by="sort_order asc, title asc",
		ignore_permissions=True,
	)
	return {"characters": [_character_dict(c) for c in characters]}
