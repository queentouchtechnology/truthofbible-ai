"""Bible Themes — a curated set of Biblical themes, browsed by every
logged-in user via this module.

`TOB Bible Theme` is closed to raw `/api/resource/...` REST for every role
except System Manager — same reasoning as `api/bible_places.py`: this file
is the only door. The content set is small and static (dozens of rows,
admin-curated), so the app fetches it in full and filters/searches
client-side rather than round-tripping per keystroke — `list_themes`
intentionally takes no search/filter params.
"""

import frappe


def _theme_dict(t) -> dict:
	return {
		"theme": t.name,
		"title": t.title,
		"weight": t.weight,
		"description": t.description or "",
		"relevant_passages": [line.strip() for line in (t.relevant_passages or "").splitlines() if line.strip()],
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def list_themes():
	themes = frappe.get_all(
		"TOB Bible Theme",
		filters={"status": "Published"},
		fields=["name", "title", "weight", "description", "relevant_passages"],
		order_by="sort_order asc, title asc",
		ignore_permissions=True,
	)
	return {"themes": [_theme_dict(t) for t in themes]}
