"""Elasticsearch-style ranking for the unified search — a port of the app's
lib/src/users/bible/ai/search/search_engine.dart, so web and app rank alike.

Every query word must match (AND). Per word: exact 10 > prefix 7–9 > inside a word 4 > typo
(edit distance 1, or 2 for words of 7+ letters) 2–5. Title words weigh 1.6×; an exact title +25,
a title starting with the query +10; shorter titles win ties. Tamil and other scripts pass through
normalisation unchanged (only Latin case/accents are folded)."""

import re
import unicodedata

_SPLIT = re.compile(r"[^0-9a-z\u0080-\U0010ffff]+")


def normalize(s: str) -> str:
	s = (s or "").lower()
	# Fold Latin accents only (é -> e); leave combining marks of other scripts (Tamil vowel signs) alone.
	s = "".join(
		unicodedata.normalize("NFD", ch)[0] if "LATIN" in unicodedata.name(ch, "") else ch
		for ch in s
	)
	return " ".join(t for t in _SPLIT.split(s) if t)


def tokens(s: str) -> list[str]:
	n = normalize(s)
	return n.split(" ") if n else []


def edit_distance(a: str, b: str, max_d: int = 2) -> int:
	"""Damerau-Levenshtein with adjacent transpositions, stopping once it exceeds max_d."""
	if abs(len(a) - len(b)) > max_d:
		return max_d + 1
	if a == b:
		return 0
	n, m = len(a), len(b)
	prev2 = [0] * (m + 1)
	prev = list(range(m + 1))
	for i in range(1, n + 1):
		cur = [i] + [0] * m
		row_min = i
		for j in range(1, m + 1):
			cost = 0 if a[i - 1] == b[j - 1] else 1
			v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
			if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
				v = min(v, prev2[j - 2] + 1)
			cur[j] = v
			row_min = min(row_min, v)
		if row_min > max_d:
			return max_d + 1
		prev2, prev = prev, cur
	return prev[m]


def allowed_typos(word: str) -> int:
	return 2 if len(word) >= 7 else 1 if len(word) >= 5 else 0


def word_score(q: str, w: str) -> float:
	if w == q:
		return 10
	if w.startswith(q):
		return 7 + 2 * (len(q) / len(w))
	if len(q) >= 3 and q in w:
		return 4
	t = allowed_typos(q)
	if t:
		d = edit_distance(q, w, t)
		if d <= t:
			return 5 - 1.5 * d
		if len(w) > len(q):
			dp = edit_distance(q, w[: len(q)], t)
			if dp <= t and dp < len(q) / 3:
				return 3.5 - dp
	return 0


class Doc:
	__slots__ = ("type", "title", "subtitle", "data", "_title_norm", "_title", "_other")

	def __init__(self, type, title, subtitle="", keywords=(), data=None):
		self.type, self.title, self.subtitle, self.data = type, title, subtitle, data
		self._title_norm = normalize(title)
		self._title = tokens(title)
		self._other = [t for k in (subtitle, *keywords) for t in tokens(k)]


_VOCAB = {}


def _vocab(docs):
	"""Distinct words of these docs, grouped by first character (typos are only looked for among words
	sharing the first letter, which keeps a pure-Python ranker fast over ~10k titles)."""
	key = (id(docs), len(docs))
	if key not in _VOCAB:
		words = {w for d in docs for w in (*d._title, *d._other)}
		by_first = {}
		for w in words:
			by_first.setdefault(w[0], []).append(w)
		_VOCAB.clear()
		_VOCAB[key] = (words, by_first)
	return _VOCAB[key]


def _scores(q, docs):
	"""word -> score for one query word, computed once per distinct word instead of per doc."""
	words, by_first = _vocab(docs)
	out = {}
	if q in words:
		out[q] = 10
	for w in words if len(q) >= 3 else by_first.get(q[0], ()):
		if w.startswith(q) or (len(q) >= 3 and q in w):
			out[w] = word_score(q, w)
	if allowed_typos(q):
		for w in by_first.get(q[0], ()):
			if w not in out:
				sc = word_score(q, w)
				if sc:
					out[w] = sc
	return out


def search(docs, query: str, limit=50):
	q_tokens = tokens(query)
	if not q_tokens:
		return []
	q_norm = " ".join(q_tokens)
	per_word = [_scores(q, docs) for q in q_tokens]
	hits = []
	for doc in docs:
		total = 0.0
		for sc in per_word:
			best = max((sc.get(w, 0) * 1.6 for w in doc._title), default=0)
			best = max(best, max((sc.get(w, 0) for w in doc._other), default=0))
			if not best:
				break
			total += best
		else:
			if doc._title_norm == q_norm:
				total += 25
			if doc._title_norm.startswith(q_norm):
				total += 10
			total -= len(doc._title) * 0.2
			hits.append((total, doc))
	hits.sort(key=lambda h: -h[0])
	return hits[:limit]


def suggest(docs, query: str):
	"""'Did you mean …?' — the closest title words to the query's words, or None."""
	q_tokens = tokens(query)
	if not q_tokens:
		return None
	vocab = {t for d in docs for t in d._title}
	by_first = {}
	for w in vocab:
		by_first.setdefault(w[0], []).append(w)
	out, changed = [], False
	for q in q_tokens:
		if q in vocab or len(q) < 4:
			out.append(q)
			continue
		best, best_d = None, 99
		for w in by_first.get(q[0], ()):
			d = edit_distance(q, w, 2)
			if d < best_d or (d == best_d and best and len(w) < len(best)):
				best, best_d = w, d
		if best and best_d <= min(2, max(1, allowed_typos(q))):
			out.append(best)
			changed = True
		else:
			out.append(q)
	return " ".join(out) if changed else None
