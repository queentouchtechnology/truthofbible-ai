"""Indian languages typed in English letters, for search: "anbu" -> அன்பு (Tamil), "sneham" -> സ്നേഹം
(Malayalam), "prem" -> प्रेम (Hindi), "yesu" -> యేసు (Telugu), and so on for every Indian script we have
a Bible in.

Such typing is ambiguous — n can be ந/ன/ண, t can be ट/त, e can be ए/ई — so every reading is tried,
letter by letter, and kept only while it is still the beginning of a word that really occurs in that
language's Bible. The surviving spellings are ranked by how common they are.
"""

import bisect
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Script:
	lang: str
	language: str
	letters: str  # regex of the script's letters, for building the vocabulary
	vowels: list  # (latin, independent letter, sign after a consonant)
	consonants: list  # (latin, consonant without vowel)
	virama: str
	inserted: tuple = ()  # vowel signs slipped between clustered consonants ("" = the inherent a: parmeshwar -> परमेश्वर)
	finals: list = field(default_factory=list)  # (latin, letter that closes a syllable): anusvara, Malayalam chillu
	initials: list = field(default_factory=list)  # (latin, letters, ends bare) only at a word's start
	geminate: str = ""  # a mark that doubles the next consonant (Gurmukhi adhak ੱ)

	@property
	def closing(self) -> str:
		return "".join(letter for _, letter in self.finals)


TAMIL = Script(
	"ta", "Tamil", r"[஀-௿]+",
	vowels=[
		("aa", "ஆ", "ா"), ("ae", "ஏ", "ே"), ("ai", "ஐ", "ை"), ("au", "ஔ", "ௌ"), ("ee", "ஈ", "ீ"), ("ee", "ஏ", "ே"),
		("ii", "ஈ", "ீ"), ("oo", "ஊ", "ூ"), ("oo", "ஓ", "ோ"), ("uu", "ஊ", "ூ"),
		("a", "அ", ""), ("a", "ஆ", "ா"), ("i", "இ", "ி"), ("i", "ஈ", "ீ"), ("u", "உ", "ு"), ("u", "ஊ", "ூ"),
		("e", "எ", "ெ"), ("e", "ஏ", "ே"), ("o", "ஒ", "ொ"), ("o", "ஓ", "ோ"),
		("y", "இ", "ி"),  # word-final y: "kanny" style spellings
	],
	consonants=[
		("ksh", "க்ஷ"), ("ng", "ங"), ("nj", "ஞ"), ("ny", "ஞ"), ("zh", "ழ"), ("sh", "ஷ"), ("ch", "ச"), ("th", "த"),
		("dh", "த"), ("tr", "ற்ற"), ("kh", "க"), ("gh", "க"), ("ph", "ப"), ("bh", "ப"),
		("k", "க"), ("g", "க"), ("c", "ச"), ("s", "ச"), ("s", "ஸ"), ("j", "ஜ"), ("j", "ச"), ("t", "ட"), ("t", "த"),
		("t", "ற"), ("d", "ட"), ("d", "த"), ("n", "ன"), ("n", "ந"), ("n", "ண"), ("p", "ப"), ("b", "ப"),
		("m", "ம"), ("y", "ய"), ("r", "ர"), ("r", "ற"), ("l", "ல"), ("l", "ள"), ("v", "வ"), ("w", "வ"),
		("h", "ஹ"), ("h", "க"), ("f", "ஃப"), ("q", "க"), ("x", "க்ஸ"), ("z", "ஜ"),
	],
	virama="்",
	inserted=("ி", "ு"),  # abraham -> ஆபிரகாம்
	initials=[("ye", "இய", True), ("ya", "இய", True), ("yo", "இய", True)],  # yesu -> இயேசு
)

MALAYALAM = Script(
	"ml", "Malayalam", r"[ഀ-ൿ]+",
	vowels=[
		("aa", "ആ", "ാ"), ("ae", "ഏ", "േ"), ("ai", "ഐ", "ൈ"), ("au", "ഔ", "ൌ"), ("ee", "ഈ", "ീ"), ("ee", "ഏ", "േ"),
		("ii", "ഈ", "ീ"), ("oo", "ഊ", "ൂ"), ("oo", "ഓ", "ോ"), ("uu", "ഊ", "ൂ"), ("ru", "ഋ", "ൃ"), ("ri", "ഋ", "ൃ"),
		("a", "അ", ""), ("a", "ആ", "ാ"), ("i", "ഇ", "ി"), ("i", "ഈ", "ീ"), ("u", "ഉ", "ു"), ("u", "ഊ", "ൂ"),
		("e", "എ", "െ"), ("e", "ഏ", "േ"), ("o", "ഒ", "ൊ"), ("o", "ഓ", "ോ"),
	],
	consonants=[
		("ksh", "ക്ഷ"), ("chh", "ഛ"), ("nj", "ഞ"), ("ny", "ഞ"), ("ng", "ങ"), ("zh", "ഴ"), ("sh", "ശ"), ("sh", "ഷ"),
		("ch", "ച"), ("th", "ത"), ("th", "ഥ"), ("th", "ത്ഥ"), ("dh", "ദ"), ("dh", "ധ"), ("dh", "ദ്ധ"), ("tt", "റ്റ"),
		("nt", "ന്റ"), ("kh", "ഖ"), ("gh", "ഘ"), ("jh", "ഝ"), ("ph", "ഫ"), ("bh", "ഭ"),
		("k", "ക"), ("g", "ഗ"), ("c", "ക"), ("c", "ച"), ("s", "സ"), ("s", "ശ"), ("j", "ജ"), ("t", "ട"), ("t", "ത"),
		("d", "ഡ"), ("d", "ദ"), ("n", "ന"), ("n", "ണ"), ("p", "പ"), ("b", "ബ"), ("m", "മ"), ("y", "യ"),
		("r", "ര"), ("r", "റ"), ("l", "ല"), ("l", "ള"), ("v", "വ"), ("w", "വ"), ("h", "ഹ"), ("f", "ഫ"),
		("q", "ക"), ("x", "ക്സ"), ("z", "സ"),
	],
	virama="്",
	inserted=("ി", "ു"),
	# a consonant that closes a syllable: dhaivam -> ദൈവം, avan -> അവൻ, avar -> അവർ, ennal -> എന്നാൽ;
	# the 1910 Bible's dot reph: prarthana -> പ്രാൎത്ഥന
	finals=[("m", "ം"), ("n", "ൻ"), ("n", "ൺ"), ("r", "ർ"), ("r", "ൎ"), ("l", "ൽ"), ("l", "ൾ")],
)


def _indic(lang, language, block, south=False, extra=(), finals=(), inserted=None, geminate=""):
	"""The other Indian scripts share one layout (each letter at the same offset in its Unicode block),
	so one table, written as Devanagari offsets, serves them all."""
	ch = lambda *offs: "".join(chr(block + o) for o in offs)  # noqa: E731
	vir = 0x4D
	vowels = [
		("aa", ch(0x06), ch(0x3E)), ("ai", ch(0x10), ch(0x48)), ("au", ch(0x14), ch(0x4C)),
		("ee", ch(0x08), ch(0x40)), ("ii", ch(0x08), ch(0x40)), ("oo", ch(0x0A), ch(0x42)), ("uu", ch(0x0A), ch(0x42)),
		("ri", ch(0x0B), ch(0x43)), ("ru", ch(0x0B), ch(0x43)),
		("a", ch(0x05), ""), ("a", ch(0x06), ch(0x3E)), ("i", ch(0x07), ch(0x3F)), ("i", ch(0x08), ch(0x40)),
		("u", ch(0x09), ch(0x41)), ("u", ch(0x0A), ch(0x42)),
	]
	if south:  # Telugu, Kannada: short and long e/o
		vowels += [("e", ch(0x0E), ch(0x46)), ("e", ch(0x0F), ch(0x47)), ("ee", ch(0x0F), ch(0x47)), ("ae", ch(0x0F), ch(0x47)),
			("o", ch(0x12), ch(0x4A)), ("o", ch(0x13), ch(0x4B)), ("oo", ch(0x13), ch(0x4B))]
	else:  # one e, one o; Hinglish "e" is often ई too: yeshu -> यीशु
		vowels += [("e", ch(0x0F), ch(0x47)), ("e", ch(0x08), ch(0x40)), ("ae", ch(0x0F), ch(0x47)), ("ee", ch(0x0F), ch(0x47)),
			("o", ch(0x13), ch(0x4B)), ("oo", ch(0x13), ch(0x4B))]
	consonants = [
		("ksh", ch(0x15, vir, 0x37)), ("chh", ch(0x1B)), ("kh", ch(0x16)), ("gh", ch(0x18)), ("ch", ch(0x1A)), ("jh", ch(0x1D)),
		("th", ch(0x24)), ("th", ch(0x25)), ("th", ch(0x20)), ("dh", ch(0x26)), ("dh", ch(0x27)), ("dh", ch(0x22)),
		("ph", ch(0x2B)), ("bh", ch(0x2D)), ("sh", ch(0x36)), ("sh", ch(0x37)), ("ng", ch(0x19)), ("ny", ch(0x1E)), ("nj", ch(0x1E)),
		("tr", ch(0x24, vir, 0x30)), ("k", ch(0x15)), ("c", ch(0x15)), ("c", ch(0x1A)), ("g", ch(0x17)), ("j", ch(0x1C)),
		("t", ch(0x24)), ("t", ch(0x1F)), ("d", ch(0x26)), ("d", ch(0x21)), ("n", ch(0x28)), ("n", ch(0x23)), ("p", ch(0x2A)),
		("f", ch(0x2B)), ("b", ch(0x2C)), ("m", ch(0x2E)), ("y", ch(0x2F)), ("r", ch(0x30)), ("l", ch(0x32)), ("l", ch(0x33)),
		("v", ch(0x35)), ("v", ch(0x2C)), ("w", ch(0x35)), ("s", ch(0x38)), ("s", ch(0x36)), ("h", ch(0x39)), ("z", ch(0x1C)),
		("q", ch(0x15)), ("x", ch(0x15, vir, 0x38)),
		*extra,
	]
	return Script(
		lang, language, f"[{chr(block)}-{chr(block + 0x7F)}]+", vowels, consonants, ch(vir),
		inserted=("",) if inserted is None and not south else (inserted or ()),
		finals=[("m", ch(0x02)), ("n", ch(0x02)), ("n", ch(0x01)), *finals],
		geminate=geminate,
	)


HINDI = _indic("hi", "Hindi", 0x0900)
MARATHI = _indic("mr", "Marathi", 0x0900)
NEPALI = _indic("ne", "Nepali", 0x0900)
BENGALI = _indic("bn", "Bengali", 0x0980, extra=[("j", "য"), ("y", "য়")])
ASSAMESE = _indic("as", "Assamese", 0x0980, extra=[("j", "য"), ("y", "য়"), ("r", "ৰ"), ("w", "ৱ"), ("v", "ৱ")])
PUNJABI = _indic("pa", "Punjabi", 0x0A00, finals=[("n", "ੰ"), ("m", "ੰ")], geminate="ੱ")
GUJARATI = _indic("gu", "Gujarati", 0x0A80)
ODIA = _indic("or", "Odia", 0x0B00, extra=[("y", "ୟ"), ("w", "ୱ")])
TELUGU = _indic("te", "Telugu", 0x0C00, south=True)
KANNADA = _indic("kn", "Kannada", 0x0C80, south=True)

SCRIPTS = {s.lang: s for s in (TAMIL, MALAYALAM, HINDI, MARATHI, NEPALI, BENGALI, ASSAMESE, PUNJABI, GUJARATI, ODIA, TELUGU, KANNADA)}
_LATIN = re.compile(r"^[a-z]+$")


class Vocab:
	"""Words of one language's Bibles with counts, sorted for prefix look-ups (in memory)."""

	def __init__(self, counts: dict[str, int]):
		self.words = sorted(counts)
		self.counts = counts

	def count(self, w: str) -> int:
		return self.counts.get(w, 0)

	def has_prefix(self, p: str) -> bool:
		i = bisect.bisect_left(self.words, p)
		return i < len(self.words) and self.words[i].startswith(p)

	def best_with_prefix(self, p: str) -> int:
		"""How common the most common word starting with p is (0 if none)."""
		return max((self.counts[w] for w in self._starting(p)), default=0)

	def completions(self, p: str, n=4) -> list[str]:
		"""The n most common words starting with p."""
		return sorted(self._starting(p), key=lambda w: -self.counts[w])[:n]

	def _starting(self, p, cap=2000):  # very short prefixes match thousands of words; a sample is enough
		i = bisect.bisect_left(self.words, p)
		out = []
		while i < len(self.words) and self.words[i].startswith(p) and len(out) < cap:
			out.append(self.words[i])
			i += 1
		return out


class SqlVocab:
	"""The same, read from the database's vocab table (built by build.py), so nothing is held in memory."""

	def __init__(self, con, lang: str):
		self.con, self.lang = con, lang

	def _range(self, p):
		return (self.lang, p, p + "\U0010ffff")

	def count(self, w: str) -> int:
		r = self.con.execute("SELECT n FROM vocab WHERE lang=? AND word=?", (self.lang, w)).fetchone()
		return r[0] if r else 0

	def has_prefix(self, p: str) -> bool:
		return self.con.execute("SELECT 1 FROM vocab WHERE lang=? AND word>=? AND word<? LIMIT 1", self._range(p)).fetchone() is not None

	def best_with_prefix(self, p: str) -> int:
		r = self.con.execute("SELECT max(n) FROM (SELECT n FROM vocab WHERE lang=? AND word>=? AND word<? LIMIT 2000)", self._range(p)).fetchone()
		return r[0] or 0

	def completions(self, p: str, n=4) -> list[str]:
		return [w for (w,) in self.con.execute(
			"SELECT word FROM (SELECT word, n FROM vocab WHERE lang=? AND word>=? AND word<? LIMIT 2000) ORDER BY n DESC LIMIT ?",
			(*self._range(p), n))]


def is_tanglish(text: str) -> bool:
	"""English letters only: maybe an Indian language typed in English."""
	return bool(text) and all(_LATIN.match(w) for w in text.lower().split())


def transliterate(word: str, vocab, script: Script = TAMIL, limit=3, max_states=4000) -> list[str]:
	"""Spellings of one typed word that start a real word of the script's Bible, most common first."""
	word = re.sub(r"[^a-z]", "", word.lower())
	if not word:
		return []
	virama, closing = script.virama, script.closing
	# state: (position in latin, native text so far, ends with a bare consonant waiting for its vowel)
	states = [(0, "", False)]
	done = []
	seen = set()
	prefix_ok = {}

	def ok(t):
		if t not in prefix_ok:
			prefix_ok[t] = vocab.has_prefix(t)
		return prefix_ok[t]

	while states and len(seen) < max_states:
		pos, text, bare = states.pop()
		if (pos, text, bare) in seen:
			continue
		seen.add((pos, text, bare))
		if pos == len(word):
			done.append(text + virama if bare else text)
			continue
		rest = word[pos:]
		base = text + virama if bare else text
		nxt = []
		for lat, letter, sign in script.vowels:
			if rest.startswith(lat):
				nxt.append((pos + len(lat), text + (sign if bare else letter), False))
		if pos == 0:
			for lat, letters, ends_bare in script.initials:
				if rest.startswith(lat):
					nxt.append((len(lat) - 1, letters, ends_bare))
		closed = bare or (text and text[-1] in closing)  # after കർ as after க்: karthavu -> കർത്താവു
		for lat, cons in script.consonants:
			if rest.startswith(lat):
				nxt.append((pos + len(lat), base + cons, True))
				# a consonant written double where English spells it once: karthar -> கர்த்தர்
				if closed and len(cons) == 1:
					nxt.append((pos + len(lat), base + cons + virama + cons, True))
				if script.geminate and not bare and pos:
					nxt.append((pos + len(lat), text + script.geminate + cons, True))
		if pos and not bare:
			for lat, letter in script.finals:
				if rest.startswith(lat):
					nxt.append((pos + len(lat), text + letter, False))
		if bare and rest[0] not in "aeiouy":
			for sign in script.inserted:
				nxt.append((pos, text + sign, False))
		for state in nxt:
			# keep only readings that are still the beginning of a real word
			if ok(state[1]):
				states.append(state)
	scored = {}
	for t in done:
		for cand in (t, t[:-1] if t.endswith(virama) else None):  # "anbu" final vowel / "devan" final pulli
			if cand and ok(cand):
				score = vocab.count(cand) * 10 + vocab.best_with_prefix(cand)
				scored[cand] = max(scored.get(cand, 0), score)
	return [w for w, _ in sorted(scored.items(), key=lambda x: -x[1])][:limit]


def to_tamil(word: str, vocab, limit=3) -> list[str]:
	return transliterate(word, vocab, TAMIL, limit)


def suggest(word: str, vocab, limit=6, script: Script = TAMIL) -> list[str]:
	"""Whole words for what has been typed so far, like a phonetic keyboard: "anb" -> அன்பு, ..."""
	words = {}
	for c in transliterate(word, vocab, script, limit=4):
		for w in ([c] if vocab.count(c) else []) + vocab.completions(c, 4):
			words[w] = vocab.count(w)
	return sorted(words, key=lambda w: -words[w])[:limit]
