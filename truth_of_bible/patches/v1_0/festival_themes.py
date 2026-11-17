"""Festival themes: the TOB Festival Theme list with the coming Christian festivals (Advent 2026 → Pentecost 2027),
behind TOB Website Settings → Festival Themes = Admins only until it is switched to Everyone. India time.
Harvest Thanksgiving is added Off: each church keeps it on its own date."""

import frappe

# (title, scene, start, end, on, greeting, greeting_ta, message, message_ta, reference, book, chapter, from, to)
FESTIVALS = [
	("Advent 2026", "Advent", "2026-11-29 00:00:00", "2026-12-23 23:59:59", 1,
		"A blessed Advent", "திருவருகைக் கால வாழ்த்துக்கள்",
		"The Light is coming. Prepare him room.", "ஒளி வருகிறது; அவருக்கு இடம் ஆயத்தம் செய்யுங்கள்.",
		"Isaiah 9:2", 23, 9, 2, 2),
	("Christmas 2026", "Christmas", "2026-12-24 00:00:00", "2026-12-30 23:59:59", 1,
		"Merry Christmas", "இனிய கிறிஸ்துமஸ் வாழ்த்துக்கள்",
		"Joy to the world, the Lord is come.", "உலகிற்கு மகிழ்ச்சி, கர்த்தர் வந்தார்.",
		"Luke 2:11", 42, 2, 11, 11),
	("New Year 2027", "New Year", "2026-12-31 18:00:00", "2027-01-03 23:59:59", 1,
		"Happy New Year", "இனிய புத்தாண்டு வாழ்த்துக்கள்",
		"His mercies are new every morning.", "அவருடைய இரக்கங்கள் காலைதோறும் புதியவைகள்.",
		"Lamentations 3:22-23", 25, 3, 22, 23),
	("Harvest Thanksgiving 2027", "Harvest Thanksgiving", "2027-01-14 00:00:00", "2027-01-17 23:59:59", 0,
		"Harvest Thanksgiving", "அறுவடைப் பண்டிகை",
		"Give thanks for every blessing of the year.", "இந்த ஆண்டின் எல்லா ஆசீர்வாதங்களுக்காகவும் நன்றி செலுத்துங்கள்.",
		"Psalm 65:11", 19, 65, 11, 11),
	("Palm Sunday 2027", "Palm Sunday", "2027-03-21 00:00:00", "2027-03-21 23:59:59", 1,
		"Hosanna!", "ஓசன்னா!",
		"Blessed is he that cometh in the name of the Lord.", "கர்த்தருடைய நாமத்தினாலே வருகிறவர் ஸ்தோத்திரிக்கப்பட்டவர்.",
		"Matthew 21:9", 40, 21, 9, 9),
	("Good Friday 2027", "Good Friday", "2027-03-26 00:00:00", "2027-03-26 23:59:59", 1,
		"Good Friday", "புனித வெள்ளி",
		"He was wounded for our transgressions.", "நம்முடைய மீறுதல்களினிமித்தம் அவர் காயப்பட்டார்.",
		"Isaiah 53:5", 23, 53, 5, 5),
	("Easter 2027", "Easter", "2027-03-28 00:00:00", "2027-04-04 23:59:59", 1,
		"He is risen!", "அவர் உயிர்த்தெழுந்தார்!",
		"Happy Easter. Christ is risen indeed.", "இனிய உயிர்த்தெழுதல் திருநாள் வாழ்த்துக்கள்.",
		"Matthew 28:6", 40, 28, 6, 6),
	("Ascension 2027", "Ascension", "2027-05-06 00:00:00", "2027-05-06 23:59:59", 1,
		"Ascension Day", "பரமேறுதல் திருநாள்",
		"This same Jesus shall so come.", "இந்த இயேசு மறுபடியும் வருவார்.",
		"Acts 1:11", 44, 1, 11, 11),
	("Pentecost 2027", "Pentecost", "2027-05-16 00:00:00", "2027-05-16 23:59:59", 1,
		"Happy Pentecost", "பெந்தெகொஸ்தே திருநாள் வாழ்த்துக்கள்",
		"They were all filled with the Holy Ghost.", "அவர்கள் எல்லாரும் பரிசுத்த ஆவியினாலே நிரப்பப்பட்டார்கள்.",
		"Acts 2:4", 44, 2, 4, 4),
]


def execute():
	# Patches run before the doctype sync, so the new doctype has to be loaded here first.
	frappe.reload_doc("truth_of_bible", "doctype", "tob_festival_theme")
	frappe.reload_doc("truth_of_bible", "doctype", "tob_website_settings")

	for (title, scene, start, end, on, greeting, greeting_ta, message, message_ta, ref, book, chapter, v1, v2) in FESTIVALS:
		if frappe.db.exists("TOB Festival Theme", title):
			continue
		frappe.get_doc({
			"doctype": "TOB Festival Theme", "title": title, "scene": scene, "start": start, "end": end, "enabled": on,
			"show_in_app": 1, "show_on_website": 1, "app_intro": 0 if scene == "Good Friday" else 1,
			"motion": "Gentle" if scene == "Good Friday" else "Normal",
			"greeting": greeting, "greeting_ta": greeting_ta, "message": message, "message_ta": message_ta,
			"verse_reference": ref, "bible_book": book, "chapter": chapter, "verse_start": v1, "verse_end": v2,
		}).insert(ignore_permissions=True)

	if not frappe.db.get_single_value("TOB Website Settings", "festival_themes"):
		frappe.db.set_single_value("TOB Website Settings", "festival_themes", "Admins only")
