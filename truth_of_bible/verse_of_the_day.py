"""Verse of the Day: one pinned row per calendar date (TOB Verse of the Day) holding the blessing verse, its background
and the app feature line. Everything that shows "today's verse" reads it — the app's popup, Home card, Daily Verse
screen and wallpapers, the website popup and the Verse Wallpapers history — so every screen and every phone agree.

Pinning matters because the pick used to be `day-of-year % published verses`: publishing a verse mid-day changed that
day's verse for everyone who hadn't cached it yet. A pinned day never changes unless someone edits its row.

Verse text is never returned: the app reads it from the Bible translation on the phone."""

from datetime import date, timedelta

import frappe
from frappe.utils import get_url, getdate, today

DOCTYPE = "TOB Verse of the Day"
DAYS_AHEAD = 30
HISTORY_PAGE = 30
ALTERNATIVES = 4


def for_date(day: date) -> dict | None:
	"""The day's verse, pinning it first if needed. None when no blessing verse is published."""
	name = frappe.db.get_value(DOCTYPE, {"date": day}) or _pin(day)
	return _payload(frappe.get_doc(DOCTYPE, name)) if name else None


def pin_ahead() -> None:
	"""Daily job: keeps the next DAYS_AHEAD days pinned, so changes to a coming day can be made in the desk."""
	start = getdate(today())
	for i in range(DAYS_AHEAD + 1):
		day = start + timedelta(days=i)
		if not frappe.db.exists(DOCTYPE, {"date": day}):
			_pin(day)
	frappe.db.commit()


def history(before: date, limit: int = HISTORY_PAGE) -> list[dict]:
	"""Pinned days before `before`, newest first. Never later than tomorrow on the server's calendar, so future verses
	stay a surprise (a phone a few hours ahead of the server still sees its own today)."""
	latest = getdate(today()) + timedelta(days=1)
	before = min(before, latest + timedelta(days=1))
	names = frappe.get_all(DOCTYPE, filters={"date": ["<", before]}, order_by="date desc", limit=limit, pluck="name")
	return [_payload(frappe.get_doc(DOCTYPE, n)) for n in names]


def _pin(day: date) -> str | None:
	verses = frappe.get_all("TOB Blessing Verse", filters={"status": "Published"}, order_by="creation asc", pluck="name")
	if not verses:
		return None
	# Same rotation as before pinning existed, so the day this ships keeps the verse people already saw.
	verse = frappe.get_doc("TOB Blessing Verse", verses[day.timetuple().tm_yday % len(verses)])
	doc = frappe.get_doc({
		"doctype": DOCTYPE,
		"date": day,
		"blessing_verse": verse.name,
		"background": _background_for(verse, day),
		"feature": _feature_for(day),
	})
	try:
		doc.insert(ignore_permissions=True)
		# Pinned from GET requests too (the website popup), which Frappe would otherwise roll back.
		frappe.db.commit()
	except frappe.DuplicateEntryError:  # another request pinned it first
		frappe.db.rollback()
		return frappe.db.get_value(DOCTYPE, {"date": day})
	return doc.name


def _active_backgrounds() -> list[dict]:
	return frappe.get_all("TOB Verse Background", filters={"status": "Active", "image": ["is", "set"]},
		fields=["name", "theme", "shows_jesus"], order_by="name asc")


def _background_for(verse, day: date) -> str | None:
	"""The verse's Preferred Background; else one matching its theme (Sundays prefer one showing Jesus); else a
	landscape from any theme. Rotates by date so a theme's pictures take turns."""
	active = _active_backgrounds()
	names = {b.name for b in active}
	if verse.get("background") in names:
		return verse.background
	same = [b for b in active if b.theme == verse.theme]
	if day.weekday() == 6:
		same = [b for b in same if b.shows_jesus] or same
	pool = same or [b for b in active if not b.shows_jesus] or active
	return pool[day.toordinal() % len(pool)].name if pool else None


def _feature_for(day: date) -> str | None:
	features = frappe.get_all("TOB App Feature", filters={"enabled": 1, "show_in_verse_popup": 1},
		order_by="sort_order asc, name asc", pluck="name")
	return features[day.toordinal() % len(features)] if features else None


def _image(name: str | None) -> dict | None:
	if not name:
		return None
	b = frappe.db.get_value("TOB Verse Background", name, ["name", "image", "text_position", "shows_jesus", "theme"], as_dict=True)
	if not b or not b.image:
		return None
	return {"title": b.name, "url": get_url(b.image), "text_position": b.text_position or "Middle",
		"shows_jesus": bool(b.shows_jesus), "theme": b.theme}


def _alternatives(chosen: str | None, theme: str | None) -> list[dict]:
	"""Other pictures for the popup's background picker: same theme first, then landscapes."""
	active = [b for b in _active_backgrounds() if b.name != chosen]
	active.sort(key=lambda b: (b.theme != theme, bool(b.shows_jesus), b.name))
	return [i for i in (_image(b.name) for b in active[:ALTERNATIVES]) if i]


def _payload(row) -> dict:
	verse = frappe.db.get_value("TOB Blessing Verse", row.blessing_verse,
		["reference", "bible_book", "chapter", "verse_start", "verse_end", "theme"], as_dict=True) or {}
	feature = None
	if row.feature:
		f = frappe.db.get_value("TOB App Feature", row.feature,
			["name", "feature_line", "feature_line_ta", "app_route", "route_id", "enabled"], as_dict=True)
		if f and f.enabled:
			feature = {"title": f.name, "line": f.feature_line, "line_ta": f.feature_line_ta or "",
				"route": f.app_route, "route_id": f.route_id or ""}
	return {
		"date": str(row.date),
		"reference": verse.get("reference"),
		"bible_book": verse.get("bible_book"),
		"chapter": verse.get("chapter"),
		"verse_start": verse.get("verse_start"),
		"verse_end": verse.get("verse_end"),
		"theme": verse.get("theme"),
		"background": _image(row.background),
		"alternatives": _alternatives(row.background, verse.get("theme")),
		"feature": feature,
	}
