"""Reading-plan catalog: a schedule generator plus the built-in plans.

`build_days(book_ids, n_days)` splits whole chapters of the given books
into `n_days` readings balanced by VERSE count (not chapter count), so a
Bible-in-a-Year day is ~85 verses whether it lands on Psalm 119 or on
three short chapters. A day can cross a book boundary ("Genesis 50;
Exodus 1–2"), which is what `segments` on TOB Reading Plan Day is for.

Plans are seeded create-only by title (`seed_catalog_plans`, after_migrate)
— an admin's edits to a seeded plan are never overwritten. Admins can also
build their own: set books + days on a plan and use "Generate days"
(api.reading_plan.generate_days).
"""

import json

import frappe

from truth_of_bible.games.arcade.content.books import BOOKS
from truth_of_bible.reading_plans.verse_counts import VERSE_COUNTS

BOOK_NAMES = {b["id"]: b["en"] for b in BOOKS}

# Gentle, open questions shown under "Reflect" for any day without its own.
REFLECTIONS = [
	"What stood out to you most in today's reading?",
	"What does this passage show you about who God is?",
	"Is there a promise here you can hold on to today?",
	"Is there a command or example here to follow?",
	"How does today's reading change how you see your day?",
	"What would you like to thank God for after reading this?",
	"Which verse would you like to remember this week?",
	"Where do you see God's faithfulness in this passage?",
	"Is there something here you don't understand yet? Write your question down.",
	"Who could you share something from today's reading with?",
	"What does this teach you about how to treat others?",
	"How could you turn today's reading into a short prayer?",
	"What does this passage show about Jesus — or point toward Him?",
	"Is there anything here that challenges you? Why?",
	"What is one small step you could take today because of this reading?",
]


def reflection_for(day_number: int) -> str:
	return REFLECTIONS[(int(day_number) - 1) % len(REFLECTIONS)]


def parse_books(spec: str) -> list[int]:
	"""'40-43' → [40, 41, 42, 43]; '45-57, 19' → [45..57, 19]; '1-66'."""
	ids: list[int] = []
	for part in (spec or "").replace(";", ",").split(","):
		part = part.strip()
		if not part:
			continue
		if "-" in part:
			a, b = (int(x) for x in part.split("-", 1))
			ids.extend(range(a, b + 1))
		else:
			ids.append(int(part))
	bad = [i for i in ids if i not in VERSE_COUNTS]
	if bad:
		raise ValueError(f"Unknown book id(s): {bad}")
	return ids


def _merge(chapters: list[tuple[int, int]]) -> list[list[int]]:
	"""[(book, ch), …] → [[book, start, end], …] for consecutive chapters."""
	segs: list[list[int]] = []
	for book, ch in chapters:
		if segs and segs[-1][0] == book and segs[-1][2] == ch - 1:
			segs[-1][2] = ch
		else:
			segs.append([book, ch, ch])
	return segs


def label_for(segments: list[list[int]]) -> str:
	parts = []
	for book, start, end in segments:
		name = BOOK_NAMES.get(book, f"Book {book}")
		parts.append(f"{name} {start}" if start == end else f"{name} {start}–{end}")
	return "; ".join(parts)


def build_days(book_ids: list[int], n_days: int) -> list[list[list[int]]]:
	"""Whole chapters of `book_ids` (in that order) split into `n_days`
	verse-balanced readings. Each day is a list of [book, start, end]."""
	chapters = [(b, c + 1, v) for b in book_ids for c, v in enumerate(VERSE_COUNTS[b])]
	if n_days < 1 or n_days > len(chapters):
		raise ValueError(f"Choose between 1 and {len(chapters)} days for these books.")
	total = sum(v for _, _, v in chapters)
	days, i, cum = [], 0, 0
	for d in range(n_days):
		remaining_days = n_days - d
		if remaining_days == 1:
			take = chapters[i:]
		else:
			target = total * (d + 1) / n_days
			take = []
			while i < len(chapters) and len(chapters) - i > remaining_days - 1:
				v = chapters[i][2]
				if take and cum + v / 2 > target:
					break
				take.append(chapters[i])
				cum += v
				i += 1
		if remaining_days == 1:
			i = len(chapters)
		days.append(_merge([(b, c) for b, c, _ in take]))
	return days


# --- built-in plans -------------------------------------------------------

# Generated: (title, books spec, days, age group, difficulty, icon, color, description)
_GENERATED = [
	("Bible in a Year", "1-66", 365, "Adults", "Deep", "menu_book", "Blue",
		"Read the whole Bible — Genesis to Revelation — in 365 days, about 15 minutes a day."),
	("New Testament in 90 Days", "40-66", 90, "Young Adults", "Moderate", "auto_stories", "Purple",
		"From Jesus' birth to the new creation: the whole New Testament in three months."),
	("The Gospels in 40 Days", "40-43", 40, "All Ages", "Easy", "favorite", "Rose",
		"Walk with Jesus through Matthew, Mark, Luke and John."),
	("Psalms in 30 Days", "19", 30, "All Ages", "Easy", "nights_stay", "Teal",
		"Prayers and songs for every season of the heart, five a day."),
	("Proverbs in 31 Days", "20", 31, "Young Adults", "Easy", "school", "Amber",
		"A chapter of wisdom for every day of the month."),
	("Acts: The Early Church in 28 Days", "44", 28, "Teens", "Easy", "volunteer_activism", "Green",
		"How the Holy Spirit spread the good news from Jerusalem to Rome."),
	("Paul's Letters in 30 Days", "45-57", 30, "Adults", "Moderate", "self_improvement", "Purple",
		"Romans to Philemon: faith, grace and life together in Christ."),
	("Genesis: Beginnings in 25 Days", "1", 25, "Teens", "Easy", "auto_stories", "Amber",
		"Creation, the fall, the flood and the stories of Abraham, Isaac, Jacob and Joseph."),
]

# Topical: (title, age, difficulty, icon, color, description, [(book, chapter, day title, reflection)])
_TOPICAL = [
	("Hope for Hard Days", "All Ages", "Easy", "favorite", "Blue",
		"Seven days of God's promises for when life feels heavy.", [
			(19, 42, "When your soul is downcast", "Where do you need to 'hope in God' today, as the psalmist does?"),
			(25, 3, "New every morning", "What mercy of God can you notice this morning?"),
			(45, 8, "Nothing can separate us", "Which of the 'nothing can separate us' lines do you most need to hear?"),
			(23, 40, "Strength for the weary", "What would it look like to 'wait upon the Lord' this week?"),
			(47, 4, "Treasure in jars of clay", "How can trouble on the outside sit alongside renewal on the inside?"),
			(19, 23, "The Lord is my shepherd", "Which line of Psalm 23 do you want to carry with you today?"),
			(66, 21, "All things new", "How does the promise of a new creation change how you face today?"),
		]),
	("Peace When You're Anxious", "All Ages", "Easy", "self_improvement", "Teal",
		"Bring your worries to God and receive His peace.", [
			(50, 4, "Do not be anxious", "What worry can you turn into a prayer with thanksgiving right now?"),
			(40, 6, "Look at the birds", "What does Jesus' care for the birds tell you about His care for you?"),
			(19, 46, "Be still", "Where could you find five minutes to 'be still' today?"),
			(43, 14, "Let not your heart be troubled", "What peace does Jesus offer that the world can't give?"),
			(23, 26, "Perfect peace", "What does it mean for your mind to be 'stayed' on God?"),
			(60, 5, "Cast your cares", "Name one care you'll hand over to God today."),
			(19, 91, "Under His wings", "Which picture of protection in Psalm 91 comforts you most?"),
		]),
	("Learning to Pray", "All Ages", "Easy", "volunteer_activism", "Purple",
		"Learn to pray from Jesus and the great prayers of Scripture.", [
			(40, 6, "The Lord's Prayer", "Pray the Lord's Prayer slowly, one line at a time."),
			(42, 11, "Ask, seek, knock", "What have you stopped asking God for? Ask again today."),
			(19, 51, "A prayer of confession", "Is there anything you need to bring honestly to God?"),
			(43, 17, "Jesus prays for us", "How does it feel to know Jesus prayed for you (verse 20)?"),
			(27, 9, "Praying for others", "Who could you pray for today the way Daniel prayed for his people?"),
			(49, 3, "A prayer for strength", "Pray Paul's prayer (verses 16–19) for someone you love."),
			(59, 5, "The prayer of faith", "What does 'the prayer of faith' look like in your life?"),
		]),
	("Forgiveness & Grace", "Adults", "Moderate", "favorite", "Rose",
		"Receive God's forgiveness — and learn to forgive.", [
			(42, 15, "The father runs", "Which son do you relate to more today — and why?"),
			(40, 18, "Seventy times seven", "Is there someone you are finding it hard to forgive?"),
			(19, 103, "As far as east from west", "How far has God removed your sins? Thank Him for it."),
			(49, 2, "Saved by grace", "What does 'not of yourselves' mean for how you see yourself?"),
			(51, 3, "Forgiving one another", "Which of the 'put on' qualities do you most need today?"),
			(1, 50, "God meant it for good", "Where have you seen God bring good out of something painful?"),
			(62, 1, "Walking in the light", "What does confession (verse 9) open the way to?"),
		]),
	("Brave Like David", "Kids", "Easy", "child_care", "Amber",
		"Seven true stories of people who trusted God and were brave.", [
			(9, 17, "David and the giant", "What 'giant' feels big to you? How is God bigger?"),
			(6, 1, "Be strong and courageous", "Where do you need to remember God is with you this week?"),
			(27, 6, "Daniel and the lions", "Daniel kept praying even when it was hard. When can you pray today?"),
			(17, 4, "Esther speaks up", "Is there someone who needs you to speak up kindly for them?"),
			(27, 3, "The fiery furnace", "Who was with the three friends in the fire? Who is with you?"),
			(7, 7, "Gideon's small army", "God won with just 300 people. Can He use you too?"),
			(44, 27, "Paul in the storm", "What can you do when you feel scared, like the sailors in the storm?"),
		]),
]


def catalog():
	"""Every built-in plan as {plan fields, days: [{…}]}."""
	plans = []
	sort = 100
	for title, spec, n, age, diff, icon, color, desc in _GENERATED:
		sort += 1
		days = []
		for i, segs in enumerate(build_days(parse_books(spec), n), start=1):
			days.append({"day_number": i, "title": "", "segments": segs, "reflection": ""})
		plans.append({
			"title": title, "age_group": age, "difficulty": diff, "icon": icon, "accent_color": color,
			"description": desc, "category": "Through the Bible" if n >= 90 else "Book Study",
			"sort_order": sort, "days": days,
		})
	for title, age, diff, icon, color, desc, entries in _TOPICAL:
		sort += 1
		days = [
			{"day_number": i, "title": t, "segments": [[b, c, c]], "reflection": r}
			for i, (b, c, t, r) in enumerate(entries, start=1)
		]
		plans.append({
			"title": title, "age_group": age, "difficulty": diff, "icon": icon, "accent_color": color,
			"description": desc, "category": "Topical", "sort_order": sort, "days": days,
		})
	return plans


def day_doc_fields(day: dict) -> dict:
	"""A catalog day → TOB Reading Plan Day fields. book_id/chapter_* keep
	the first segment, for older app builds that only know those."""
	segs = day["segments"]
	first = segs[0]
	return {
		"day_number": day["day_number"],
		"title": day.get("title") or "",
		"book_id": first[0],
		"chapter_start": first[1],
		"chapter_end": first[2],
		"reference_label": label_for(segs),
		"segments": json.dumps(segs),
		"reflection": day.get("reflection") or "",
		"note": day.get("note") or "",
	}


def seed_catalog_plans():
	"""after_migrate: create any built-in plan that doesn't exist yet (by
	title). Never touches an existing plan."""
	for entry in catalog():
		if frappe.db.exists("TOB Reading Plan", {"title": entry["title"]}):
			continue
		try:
			days = entry.pop("days")
			plan = frappe.get_doc({
				"doctype": "TOB Reading Plan", "status": "Published", "duration_days": len(days), **entry,
			})
			plan.insert(ignore_permissions=True)
			for day in days:
				frappe.get_doc({"doctype": "TOB Reading Plan Day", "plan": plan.name, **day_doc_fields(day)}).insert(
					ignore_permissions=True
				)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Reading plan seed: {entry.get('title')}", message=frappe.get_traceback())
