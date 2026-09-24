"""Pure parsing of Bible reference strings ("Psalm 23:1", "Numbers 6:24-26")
into TOB Blessing Verse's own location fields — no Frappe dependency, so it
is unit-testable directly (tests/test_verse_reference.py)."""

import re

# Same canonical English names as TOB Blessing Verse.bible_book's options,
# which must match the Flutter client's Book table exactly.
BOOKS = (
	"Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges", "Ruth",
	"1 Samuel", "2 Samuel", "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles", "Ezra",
	"Nehemiah", "Esther", "Job", "Psalms", "Proverbs", "Ecclesiastes", "Song of Solomon",
	"Isaiah", "Jeremiah", "Lamentations", "Ezekiel", "Daniel", "Hosea", "Joel", "Amos",
	"Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah",
	"Malachi", "Matthew", "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians",
	"2 Corinthians", "Galatians", "Ephesians", "Philippians", "Colossians", "1 Thessalonians",
	"2 Thessalonians", "1 Timothy", "2 Timothy", "Titus", "Philemon", "Hebrews", "James",
	"1 Peter", "2 Peter", "1 John", "2 John", "3 John", "Jude", "Revelation",
)
_ALIASES = {"Psalm": "Psalms", "Song of Songs": "Song of Solomon"}
_PATTERN = re.compile(r"^\s*(.+?)\s+(\d+):(\d+)(?:\s*-\s*(\d+))?\s*$")


def parse(reference: str):
	"""Returns {"bible_book", "chapter", "verse_start", "verse_end"} or None if
	the reference isn't a single-chapter reference to a known book."""
	match = _PATTERN.match(reference or "")
	if not match:
		return None
	book, chapter, start, end = match.groups()
	book = _ALIASES.get(book, book)
	if book not in BOOKS:
		return None
	start, end = int(start), int(end) if end else None
	if end is not None and end <= start:
		return None
	return {"bible_book": book, "chapter": int(chapter), "verse_start": start, "verse_end": end}


def canonical(parsed: dict) -> str:
	"""The display reference TOB Blessing Verse uses, e.g. 'Psalms 23:1-3'."""
	verse = f"{parsed['verse_start']}-{parsed['verse_end']}" if parsed["verse_end"] else str(parsed["verse_start"])
	return f"{parsed['bible_book']} {parsed['chapter']}:{verse}"
