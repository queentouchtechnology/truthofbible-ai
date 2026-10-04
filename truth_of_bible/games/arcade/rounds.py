"""Builds and checks the solo game rounds. The server keeps the answer key
(TOB Game Session.items) and only ever sends `public_item()` — answers
come back one at a time through `check()`, so the app can't read ahead.

Every game is bilingual: `language` is 'ta' or 'en' and picks the text
from the content banks (verse/quote text is exact Bible text, see
content/verses.py)."""

import random
import re
import unicodedata

from truth_of_bible.games.arcade.content.books import BOOKS
from truth_of_bible.games.arcade.content.characters import CHARACTERS
from truth_of_bible.games.arcade.content.quotes import QUOTES, SPEAKERS
from truth_of_bible.games.arcade.content.treasure import HUNTS
from truth_of_bible.games.arcade.content.verses import VERSES
from truth_of_bible.games.arcade.content.words import KIND_HINT, WORDS

GAMES = ("verse", "character", "who_said", "scramble", "treasure")
ROUND_SIZE = {"verse": 8, "character": 6, "who_said": 8, "scramble": 8, "treasure": 5}

_PUNCT = ".,;:!?'\"()“”‘’"
_EN_STOP = {
	"that", "which", "with", "unto", "shall", "have", "from", "them", "they", "thee", "thou", "this", "there",
	"their", "will", "been", "hath", "upon", "also", "whom", "what", "when", "were", "into", "your", "ye",
	"him", "his", "her", "for", "and", "the", "not", "but", "all", "are", "was", "who", "any", "even", "same",
	"said", "saith", "shalt", "much", "things", "thing", "every", "made", "know", "come", "cometh",
}


def letters(word: str) -> list[str]:
	"""Splits into what a reader sees as letters: a Tamil consonant keeps
	its vowel sign / pulli (combining marks join the previous letter)."""
	out: list[str] = []
	for ch in word:
		if out and unicodedata.category(ch) in ("Mn", "Mc"):
			out[-1] += ch
		else:
			out.append(ch)
	return out


def _core(token: str) -> str:
	return token.strip(_PUNCT)


def _norm(text: str) -> str:
	return re.sub(r"\s+", " ", (text or "").strip()).casefold()


_BOOK_TA = sorted(((b["en"], b["ta"]) for b in BOOKS), key=lambda x: -len(x[0])) + [("Psalm", "சங்கீதம்")]


def localize_ref(ref: str, language: str) -> str:
	"""'1 Kings 3:16–28' → 'I இராஜாக்கள் 3:16–28' for Tamil; every book
	name in a multi-part reference is translated."""
	if language != "ta" or not ref:
		return ref
	pattern = "|".join(re.escape(en) for en, _ in _BOOK_TA)
	table = dict(_BOOK_TA)
	return re.sub(rf"(?<![A-Za-z])({pattern})(?![A-Za-z])", lambda m: table[m.group(1)], ref)


def _pick_options(answer: str, pool: list[str], n: int = 3) -> list[str]:
	others = list({p for p in pool if _norm(p) != _norm(answer)})
	options = random.sample(others, min(n, len(others))) + [answer]
	random.shuffle(options)
	return options


# --- builders: each returns the stored (answer-key) item ------------------


def _blank_candidates(text: str, language: str) -> list[int]:
	tokens = text.split()
	out = []
	for i, tok in enumerate(tokens):
		core = _core(tok)
		if language == "ta":
			if 3 <= len(letters(core)) <= 10:
				out.append(i)
		elif 4 <= len(core) <= 12 and core.lower() not in _EN_STOP and core.isalpha():
			out.append(i)
	return out


def _verse_items(language: str, n: int) -> list[dict]:
	lang = language
	# Distractors are words that could themselves have been the blank.
	all_words = []
	for v in VERSES:
		tokens = v[lang].split()
		all_words += [_core(tokens[i]) for i in _blank_candidates(v[lang], lang)]
	items = []
	for v in random.sample(VERSES, n):
		text = v[lang]
		tokens = text.split()
		choices = _blank_candidates(text, lang)
		idx = random.choice(choices)
		answer = _core(tokens[idx])
		size = len(letters(answer))
		similar = [w for w in all_words if abs(len(letters(w)) - size) <= 2]
		if lang == "en" and not answer.isupper():
			# Same case as the answer, so capitals don't give it away.
			fix = (lambda w: w.capitalize()) if answer[0].isupper() else (lambda w: w.lower())
			similar = [fix(w) for w in similar if not w.isupper()]
		shown = tokens[idx].replace(answer, "_____", 1)
		items.append({
			"prompt": " ".join(tokens[:idx] + [shown] + tokens[idx + 1:]),
			"reference": v[f"ref_{lang}"],
			"options": _pick_options(answer, similar),
			"answer": answer,
			"full": text,
		})
	return items


def _character_items(language: str, n: int) -> list[dict]:
	names = [c[language] for c in CHARACTERS]
	items = []
	for c in random.sample(CHARACTERS, n):
		items.append({
			"clues": c[f"clues_{language}"],
			"options": _pick_options(c[language], names),
			"answer": c[language],
			"reference": localize_ref(c["ref"], language),
		})
	return items


def _who_said_items(language: str, n: int) -> list[dict]:
	items = []
	for q in random.sample(QUOTES, n):
		speaker = SPEAKERS[q["speaker"]][language]
		pool = [s[language] for k, s in SPEAKERS.items() if k != q["speaker"]]
		items.append({
			"quote": q[language],
			"reference": q[f"ref_{language}"],
			"options": _pick_options(speaker, pool),
			"answer": speaker,
		})
	return items


def _scramble_pool(language: str) -> list[tuple[str, str]]:
	pool = [(w[language], w["kind"]) for w in WORDS]
	for b in BOOKS:
		if " " not in b["en"] and " " not in b["ta"] and not b["en"][0].isdigit():
			pool.append((b[language], "book"))
	return [(w, k) for w, k in pool if 3 <= len(letters(w)) <= 9]


def _scramble_items(language: str, n: int) -> list[dict]:
	items = []
	for word, kind in random.sample(_scramble_pool(language), n):
		shown = word.upper() if language == "en" else word
		tiles = letters(shown)
		shuffled = tiles[:]
		for _ in range(10):
			random.shuffle(shuffled)
			if shuffled != tiles:
				break
		items.append({"tiles": shuffled, "hint": KIND_HINT[kind][language], "kind": kind, "answer": shown})
	return items


def _treasure_items(language: str, n: int) -> tuple[list[dict], dict]:
	hunt = random.choice(HUNTS)
	items = []
	for stop in hunt["stops"][:n]:
		answer = stop[f"options_{language}"][0]
		options = stop[f"options_{language}"][:]
		random.shuffle(options)
		items.append({"clue": stop[f"clue_{language}"], "options": options, "answer": answer,
			"reference": localize_ref(stop["ref"], language)})
	return items, {"hunt": hunt["key"], "title": hunt[f"title_{language}"], "icon": hunt["icon"]}


def build(game: str, language: str) -> tuple[list[dict], dict]:
	n = ROUND_SIZE[game]
	if game == "verse":
		return _verse_items(language, n), {}
	if game == "character":
		return _character_items(language, n), {}
	if game == "who_said":
		return _who_said_items(language, n), {}
	if game == "scramble":
		return _scramble_items(language, n), {}
	return _treasure_items(language, n)


# --- what the app sees ----------------------------------------------------


def public_item(item: dict) -> dict:
	return {k: v for k, v in item.items() if k not in ("answer", "full")}


def reveal(item: dict) -> dict:
	"""Shown after the player answers."""
	return {"answer": item["answer"], "full": item.get("full"), "reference": item.get("reference")}


# --- scoring ----------------------------------------------------------------


def _speed_bonus(seconds: float) -> int:
	if seconds <= 5:
		return 5
	if seconds <= 10:
		return 3
	if seconds <= 20:
		return 1
	return 0


def check(game: str, item: dict, answer: str | None, seconds: float, clues_used: int = 1, hints_used: int = 0) -> tuple[bool, int]:
	"""(correct, points). Points: a fixed base per game, plus a speed bonus
	timed by the server (time since the previous answer)."""
	correct = bool(answer) and _norm(answer) == _norm(item["answer"])
	if not correct:
		return False, 0
	if game == "character":
		base = {1: 15, 2: 10}.get(max(1, min(3, clues_used)), 6)
	elif game == "scramble":
		base = max(4, 10 - 3 * max(0, hints_used))
	elif game == "treasure":
		base = 12
	else:
		base = 10
	return True, base + _speed_bonus(seconds)
