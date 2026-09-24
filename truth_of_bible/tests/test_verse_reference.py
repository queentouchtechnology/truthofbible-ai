"""Pure-function tests for social/verse_reference.py — no Frappe/DB dependency."""

import unittest

from truth_of_bible.social.verse_reference import canonical, parse


class TestParse(unittest.TestCase):
	def test_single_verse(self):
		self.assertEqual(parse("Jeremiah 29:11"),
			{"bible_book": "Jeremiah", "chapter": 29, "verse_start": 11, "verse_end": None})

	def test_verse_range(self):
		self.assertEqual(parse("Numbers 6:24-26")["verse_end"], 26)

	def test_numbered_book(self):
		self.assertEqual(parse("2 Thessalonians 3:16")["bible_book"], "2 Thessalonians")

	def test_psalm_alias(self):
		self.assertEqual(parse("Psalm 23:1")["bible_book"], "Psalms")

	def test_unknown_book_rejected(self):
		self.assertIsNone(parse("Hezekiah 1:1"))

	def test_malformed_rejected(self):
		for ref in ("", "John 3", "John three:16", "Romans 8:28-28", "Romans 8:30-28"):
			with self.subTest(ref=ref):
				self.assertIsNone(parse(ref))


class TestCanonical(unittest.TestCase):
	def test_round_trip(self):
		for ref in ("Psalms 23:1-3", "John 3:16", "1 Peter 5:7"):
			with self.subTest(ref=ref):
				self.assertEqual(canonical(parse(ref)), ref)

	def test_alias_normalised(self):
		self.assertEqual(canonical(parse("Psalm 23:1")), "Psalms 23:1")


if __name__ == "__main__":
	unittest.main()
