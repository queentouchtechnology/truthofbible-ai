"""Tanglish -> Tamil for search: "anbu" -> அன்பு, "yesu" -> இயேசு, "devan" -> தேவன்.

Tanglish (Tamil typed with English letters) is ambiguous — n can be ந/ன/ண, t can be ட/த/ற, e can be
எ/ஏ — so every reading is tried, letter by letter, and kept only while it is still the beginning of a
word that really occurs in the Tamil Bible. The surviving spellings are ranked by how common they are.
"""

import bisect
import re

VOWELS = [  # (latin, independent letter, sign after a consonant)
	("aa", "ஆ", "ா"), ("ae", "ஏ", "ே"), ("ai", "ஐ", "ை"), ("au", "ஔ", "ௌ"), ("ee", "ஈ", "ீ"), ("ee", "ஏ", "ே"),
	("ii", "ஈ", "ீ"), ("oo", "ஊ", "ூ"), ("oo", "ஓ", "ோ"), ("uu", "ஊ", "ூ"),
	("a", "அ", ""), ("a", "ஆ", "ா"), ("i", "இ", "ி"), ("i", "ஈ", "ீ"), ("u", "உ", "ு"), ("u", "ஊ", "ூ"),
	("e", "எ", "ெ"), ("e", "ஏ", "ே"), ("o", "ஒ", "ொ"), ("o", "ஓ", "ோ"),
	("y", "இ", "ி"),  # word-final y: "kanny" style spellings
]
CONSONANTS = [  # (latin, Tamil consonant without vowel)
	("ksh", "க்ஷ"), ("ng", "ங"), ("nj", "ஞ"), ("ny", "ஞ"), ("zh", "ழ"), ("sh", "ஷ"), ("ch", "ச"), ("th", "த"),
	("dh", "த"), ("tr", "ற்ற"), ("kh", "க"), ("gh", "க"), ("ph", "ப"), ("bh", "ப"),
	("k", "க"), ("g", "க"), ("c", "ச"), ("s", "ச"), ("s", "ஸ"), ("j", "ஜ"), ("j", "ச"), ("t", "ட"), ("t", "த"),
	("t", "ற"), ("d", "ட"), ("d", "த"), ("n", "ன"), ("n", "ந"), ("n", "ண"), ("p", "ப"), ("b", "ப"),
	("m", "ம"), ("y", "ய"), ("r", "ர"), ("r", "ற"), ("l", "ல"), ("l", "ள"), ("v", "வ"), ("w", "வ"),
	("h", "ஹ"), ("h", "க"), ("f", "ஃப"), ("q", "க"), ("x", "க்ஸ"), ("z", "ஜ"),
]
PULLI = "்"
_LATIN = re.compile(r"^[a-z]+$")


class Vocab:
	"""Tamil words of the Tamil Bibles, sorted for prefix look-ups, with counts."""

	def __init__(self, counts: dict[str, int]):
		self.words = sorted(counts)
		self.counts = counts

	def has_prefix(self, p: str) -> bool:
		i = bisect.bisect_left(self.words, p)
		return i < len(self.words) and self.words[i].startswith(p)

	def best_with_prefix(self, p: str) -> int:
		"""How common the most common word starting with p is (0 if none)."""
		i = bisect.bisect_left(self.words, p)
		best = 0
		while i < len(self.words) and self.words[i].startswith(p) and best < 10**9:
			best = max(best, self.counts[self.words[i]])
			i += 1
			if i % 2000 == 0:  # very short prefixes match thousands of words; that's enough of a sample
				break
		return best

	def completions(self, p: str, n=4) -> list[str]:
		"""The n most common words starting with p."""
		i = bisect.bisect_left(self.words, p)
		found = []
		while i < len(self.words) and self.words[i].startswith(p) and len(found) < 2000:
			found.append(self.words[i])
			i += 1
		return sorted(found, key=lambda w: -self.counts[w])[:n]


def suggest(word: str, vocab: Vocab, limit=6) -> list[str]:
	"""Whole Tamil words for what has been typed so far, like a phonetic keyboard: "anb" -> அன்பு, ..."""
	words = {}
	for c in to_tamil(word, vocab, limit=4):
		for w in completions_with(c, vocab):
			words[w] = vocab.counts[w]
	return sorted(words, key=lambda w: -words[w])[:limit]


def completions_with(p: str, vocab: Vocab) -> list[str]:
	return ([p] if p in vocab.counts else []) + vocab.completions(p, 4)


def is_tanglish(text: str) -> bool:
	return bool(text) and all(_LATIN.match(w) for w in text.lower().split())


def to_tamil(word: str, vocab: Vocab, limit=3, max_states=4000) -> list[str]:
	"""Tamil spellings for one Tanglish word that start a real Tamil Bible word, most common first."""
	word = re.sub(r"[^a-z]", "", word.lower())
	if not word:
		return []
	# state: (position in latin, tamil so far, ends with a bare consonant waiting for its vowel)
	states = [(0, "", False)]
	done = []
	seen = set()
	while states and len(seen) < max_states:
		pos, tam, bare = states.pop()
		if (pos, tam, bare) in seen:
			continue
		seen.add((pos, tam, bare))
		if pos == len(word):
			done.append(tam + PULLI if bare else tam)
			continue
		rest = word[pos:]
		nxt = []
		for lat, letter, sign in VOWELS:
			if rest.startswith(lat):
				t = tam + (sign if bare else letter)
				nxt.append((pos + len(lat), t, False))
		if pos == 0 and rest[:2] in ("ye", "ya", "yo"):
			nxt.append((1, "இய", True))  # word-initial "ye": இயேசு
		for lat, cons in CONSONANTS:
			if rest.startswith(lat):
				base = tam + PULLI if bare else tam
				nxt.append((pos + len(lat), base + cons, True))
				# Tamil often doubles what English spells once: karthar -> கர்த்தர்
				if bare and len(cons) == 1:
					nxt.append((pos + len(lat), base + cons + PULLI + cons, True))
		if bare and rest[0] not in "aeiouy":
			# a vowel Tamil inserts between clustered consonants: abraham -> ஆபிரகாம்
			for sign in ("ி", "ு"):
				nxt.append((pos, tam + sign, False))
		for state in nxt:
			# keep only readings that are still the beginning of a real Tamil word
			if vocab.has_prefix(state[1] if not state[2] else state[1]):
				states.append(state)
	scored = {}
	for t in done:
		for cand in (t, t[:-1] if t.endswith(PULLI) else None):  # "anbu" final vowel / "devan" final pulli
			if cand and vocab.has_prefix(cand):
				exact = vocab.counts.get(cand, 0)
				score = exact * 10 + vocab.best_with_prefix(cand)
				scored[cand] = max(scored.get(cand, 0), score)
	return [w for w, _ in sorted(scored.items(), key=lambda x: -x[1])][:limit]
