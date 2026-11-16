"""The six backgrounds that show Jesus keep the verse in the sky (Top), never over his face; the Psalm 23 blessing
verses use the Shepherd picture. Fields added on 2026-11-16 (Text Position, Preferred Background)."""

import frappe

TOP = [
	"Golden-Hour Shepherd's Journey",
	"Jesus Praying at Sunset",
	"Jesus Walking Through Stormy Seas",
	"Moonlit Prayer in the Olive Garden",
	"Sunrise Teaching by the Lake",
	"Sunset Pilgrim Over Misty Valleys",
]
SHEPHERD = "Golden-Hour Shepherd's Journey"


def execute():
	# Patches run before the doctype sync, so the new columns have to be loaded here first.
	frappe.reload_doc("truth_of_bible", "doctype", "tob_verse_background")
	frappe.reload_doc("truth_of_bible", "doctype", "tob_blessing_verse")
	for name in frappe.get_all("TOB Verse Background", pluck="name"):
		position = "Top" if name in TOP else "Middle"
		frappe.db.set_value("TOB Verse Background", name, "text_position", position, update_modified=False)
	if frappe.db.exists("TOB Verse Background", SHEPHERD):
		for name in frappe.get_all("TOB Blessing Verse",
				filters={"bible_book": ["like", "Psalm%"], "chapter": 23, "background": ["in", ["", None]]}, pluck="name"):
			frappe.db.set_value("TOB Blessing Verse", name, "background", SHEPHERD, update_modified=False)
