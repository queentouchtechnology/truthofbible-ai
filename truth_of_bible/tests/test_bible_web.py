"""Web Bible build and query helpers (pure functions; no site or database needed).

    python -m unittest truth_of_bible.tests.test_bible_web
"""

import unittest

from truth_of_bible.bible_web.build import canon_by_name, clean
from truth_of_bible.bible_web.queries import _fts_query


class CleanTest(unittest.TestCase):
	def test_kjv_strongs_and_words_of_jesus(self):
		text, html, _ = clean("And<WG1161> Jesus<WG2424> said<WG2036>, <FR>Suffer<WG863> <FI>it to be so<Fi> now<WG737>.<Fr>")
		self.assertEqual(text, "And Jesus said, Suffer it to be so now.")
		self.assertEqual(html, 'And Jesus said, <span class="j">Suffer <i>it to be so</i> now.</span>')

	def test_footnotes_dropped_and_paragraph_flag(self):
		text, html, para = clean("<pb/>In the beginning<RF>a note<Rf> God created.<f>[1]</f>")
		self.assertEqual((text, html, para), ("In the beginning God created.", None, 1))

	def test_markup_in_text_is_escaped(self):
		text, html, _ = clean("<J>a < b & c</J>")
		self.assertEqual(text, "a < b & c")
		self.assertEqual(html, '<span class="j">a &lt; b &amp; c</span>')

	def test_unclosed_title_is_closed(self):
		_, html, _ = clean('<title type="psalm"> A Psalm of David.')
		self.assertEqual(html, '<span class="t"> A Psalm of David.</span>')


class SearchQueryTest(unittest.TestCase):
	def test_words_phrases_and_prefix(self):
		self.assertEqual(_fts_query('love "one another" sav*'), '"love" "one another" "sav"*')

	def test_fts_operators_cannot_be_injected(self):
		self.assertEqual(_fts_query('NEAR(a b) OR x:y'), '"NEARa" "b" "xy"')

	def test_prefix_languages(self):
		self.assertEqual(_fts_query("அன்பு", prefix=True), '"அன்பு"*')


class BookNameTest(unittest.TestCase):
	def test_module_spellings(self):
		self.assertEqual(canon_by_name("I Samuel"), 9)
		self.assertEqual(canon_by_name("III John"), 64)
		self.assertEqual(canon_by_name("Revelation of John"), 66)
		self.assertEqual(canon_by_name("Psalms "), 19)
		self.assertIsNone(canon_by_name("I Maccabees"))
		self.assertIsNone(canon_by_name("ஆதியாகமம்"))


class RankTest(unittest.TestCase):
	def setUp(self):
		from truth_of_bible.bible_web.rank import Doc
		self.docs = [Doc("Characters", t) for t in ("Moses", "Abraham", "Jerusalem", "John the Baptist", "Mount Moriah")]

	def titles(self, q):
		from truth_of_bible.bible_web.rank import search
		return [d.title for _, d in search(self.docs, q)]

	def test_exact_then_prefix(self):
		self.assertEqual(self.titles("mos")[0], "Moses")
		self.assertEqual(self.titles("moses"), ["Moses"])

	def test_typos_on_longer_words_only(self):
		self.assertEqual(self.titles("abrahm"), ["Abraham"])
		self.assertEqual(self.titles("jerusalm"), ["Jerusalem"])
		self.assertEqual(self.titles("jahn"), [])  # 4 letters: no typo allowed, as in the app

	def test_every_word_must_match(self):
		self.assertEqual(self.titles("john baptist"), ["John the Baptist"])
		self.assertEqual(self.titles("john moses"), [])

	def test_did_you_mean(self):
		from truth_of_bible.bible_web.rank import suggest
		self.assertEqual(suggest(self.docs, "abrahm"), "abraham")
		self.assertIsNone(suggest(self.docs, "moses"))


class TanglishTest(unittest.TestCase):
	"""Tamil typed in English letters, against a small made-up vocabulary."""

	@classmethod
	def setUpClass(cls):
		from truth_of_bible.bible_web.translit import Vocab
		cls.vocab = Vocab({"அன்பு": 50, "அன்புகூர்ந்து": 20, "அனுப்பினான்": 30, "இயேசு": 90, "கர்த்தர்": 200, "தேவன்": 120, "ஆபிரகாம்": 40})

	def test_spellings(self):
		from truth_of_bible.bible_web.translit import to_tamil
		for latin, tamil in [("anbu", "அன்பு"), ("yesu", "இயேசு"), ("karthar", "கர்த்தர்"), ("devan", "தேவன்"), ("abraham", "ஆபிரகாம்")]:
			self.assertEqual(to_tamil(latin, self.vocab)[0], tamil, latin)

	def test_only_latin_is_tanglish(self):
		from truth_of_bible.bible_web.translit import is_tanglish
		self.assertTrue(is_tanglish("yesu kristhu"))
		self.assertFalse(is_tanglish("John 3"))
		self.assertFalse(is_tanglish("அன்பு"))

	def test_suggest_while_typing(self):
		from truth_of_bible.bible_web.translit import suggest
		self.assertEqual(suggest("anb", self.vocab), ["அன்பு", "அனுப்பினான்", "அன்புகூர்ந்து"])  # most common first
		self.assertEqual(suggest("zzz", self.vocab), [])


class IndianScriptsTest(unittest.TestCase):
	"""English letters for the other Indian languages, against tiny made-up vocabularies."""

	def spell(self, lang, latin, words):
		from truth_of_bible.bible_web.translit import SCRIPTS, Vocab, transliterate
		return transliterate(latin, Vocab(dict.fromkeys(words, 10)), SCRIPTS[lang])[:1]

	def test_malayalam_chillu_and_anusvara(self):
		self.assertEqual(self.spell("ml", "sneham", ["സ്നേഹം"]), ["സ്നേഹം"])
		self.assertEqual(self.spell("ml", "avan", ["അവൻ"]), ["അവൻ"])
		self.assertEqual(self.spell("ml", "karthavu", ["കർത്താവു"]), ["കർത്താവു"])

	def test_hindi_inherent_a_and_e_as_ii(self):
		self.assertEqual(self.spell("hi", "parmeshwar", ["परमेश्वर"]), ["परमेश्वर"])
		self.assertEqual(self.spell("hi", "yeshu", ["यीशु"]), ["यीशु"])

	def test_telugu_and_kannada(self):
		self.assertEqual(self.spell("te", "devudu", ["దేవుడు"]), ["దేవుడు"])
		self.assertEqual(self.spell("kn", "devaru", ["ದೇವರು"]), ["ದೇವರು"])


class HebrewTest(unittest.TestCase):
	def test_points_and_accents_removed(self):
		from truth_of_bible.bible_web.queries import strip_marks
		self.assertEqual(strip_marks("שָׁל֥וֹם"), "שלום")

	def test_marks_move_back_to_pointed_words(self):
		from truth_of_bible.bible_web.queries import _repoint
		r = _repoint({"hit": "ויאמר <mark>שלום</mark> לך", "pointed": "וַיֹּ֥אמֶר שָׁל֥וֹם לָךְ"})
		self.assertEqual(r, {"hit": "וַיֹּ֥אמֶר <mark>שָׁל֥וֹם</mark> לָךְ"})
