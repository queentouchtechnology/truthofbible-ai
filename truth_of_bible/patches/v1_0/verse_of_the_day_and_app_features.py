"""Starts the Verse of the Day: fills TOB App Feature with the app's features (each with the screen it opens) and pins
the next 30 days. The first seven are the popup's feature lines, in the order agreed on 2026-11-16."""

import frappe

# (title, app route, popup order or None, English line, Tamil line)
FEATURES = [
	("Offline Bible", "/bible", 1, "Read it offline in 160+ translations", "160+ மொழிபெயர்ப்புகளில் இணையமின்றி வாசியுங்கள்"),
	("AI Bible Q&A", "/bibleQa", 2, "Ask any Bible question · AI answers with verses", "எந்த வேதாகமக் கேள்வியையும் கேளுங்கள் · வசனங்களுடன் பதில்"),
	("Tamil and English side by side", "/bibleCompare", 3, "Tamil and English Bible, side by side", "தமிழ் மற்றும் ஆங்கில வேதாகமம், அருகருகே"),
	("Bible Foundation course", "/courseList", 4, "52-week Bible Foundation course · free", "52 வார வேதாகம அடிப்படைப் பாடநெறி · இலவசம்"),
	("Reading plans", "/readingPlans", 5, "Daily reading plans with streaks", "தொடர் நாட்களுடன் தினசரி வாசிப்புத் திட்டங்கள்"),
	("Bible quizzes and Bible Battle", "/bibleBattle", 6, "Bible quizzes and Bible Battle", "வேதாகம வினாடி வினா மற்றும் Bible Battle"),
	("Prayer Wall", "/prayerWall", 7, "Pray together on the Prayer Wall", "ஜெப சுவரில் ஒன்றாக ஜெபியுங்கள்"),
	("Daily devotional", "/devotional", None, "A short devotional on today's verse", "இன்றைய வசனத்தின் மீது ஒரு சிறு தியானம்"),
	("Bible search", "/bibleSearch", None, "Search every verse in seconds", "எந்த வசனத்தையும் நொடியில் தேடுங்கள்"),
	("Bible places", "/biblePlaces", None, "See the Bible's places on a map", "வேதாகம இடங்களை வரைபடத்தில் காணுங்கள்"),
	("Bible journeys", "/bibleJourneys", None, "Follow the journeys of the Bible, step by step", "வேதாகமப் பயணங்களைப் படிப்படியாகப் பின்தொடருங்கள்"),
	("Bible characters", "/bibleCharacters", None, "Meet the people of the Bible", "வேதாகம மனிதர்களை அறிந்துகொள்ளுங்கள்"),
	("Church finder", "/churchFinder", None, "Find a church near you", "உங்கள் அருகிலுள்ள சபையைக் கண்டறியுங்கள்"),
	("Sunday School", "/sundaySchoolDashboard", None, "Sunday School with weekly rewards", "வாராந்திர வெகுமதிகளுடன் ஞாயிறு பள்ளி"),
	("Rewards", "/rewards", None, "Earn rewards as you read", "வாசிக்கும்போது வெகுமதிகளைப் பெறுங்கள்"),
	("Community", "/communityfeed", None, "Share and grow with the community", "சமூகத்துடன் பகிர்ந்து வளருங்கள்"),
	("Verse Wallpapers", "/verseWallpapers", None, "A new verse wallpaper every day", "ஒவ்வொரு நாளும் ஒரு புதிய வசன வால்பேப்பர்"),
]


def execute():
	# Patches run before the doctype sync, so the new doctypes have to be loaded here first.
	for dt in ("tob_app_feature", "tob_verse_of_the_day", "tob_verse_background", "tob_blessing_verse"):
		frappe.reload_doc("truth_of_bible", "doctype", dt)
	for title, route, order, line, line_ta in FEATURES:
		if frappe.db.exists("TOB App Feature", title):
			continue
		frappe.get_doc({
			"doctype": "TOB App Feature",
			"title": title,
			"enabled": 1,
			"show_in_verse_popup": 1 if order else 0,
			"sort_order": order or 100,
			"app_route": route,
			"feature_line": line,
			"feature_line_ta": line_ta,
		}).insert(ignore_permissions=True)
	from truth_of_bible.verse_of_the_day import pin_ahead

	pin_ahead()
