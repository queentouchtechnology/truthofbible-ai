"""Read-only queries over tob_bible_web.db (see build.py). Plain sqlite3, no Frappe — the API in
truth_of_bible/api/bible_web.py is a thin wrapper, and these can be tested or timed on their own."""

import re
import sqlite3
import unicodedata
from functools import lru_cache

PAGE = 30


def connect(path: str) -> sqlite3.Connection:
	con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True, check_same_thread=False)
	con.row_factory = sqlite3.Row
	con.execute("PRAGMA mmap_size=1073741824")
	con.execute("PRAGMA cache_size=-65536")
	return con


# ------------------------------------------------------------------ versions & books


def versions(con):
	return [dict(r) for r in con.execute(
		"SELECT code, name, language, lang, dir, license, attribution, note, has_strongs, verse_count FROM versions ORDER BY sort"
	)]


def _version(con, code):
	r = con.execute("SELECT * FROM versions WHERE code=?", (code,)).fetchone()
	if not r:
		raise LookupError(f"Unknown version: {code}")
	return r


def books(con, version):
	_version(con, version)
	return [dict(r) for r in con.execute(
		"""SELECT n.book, n.name, n.chapters, b.slug, b.osis, b.name AS english,
		   COALESCE(b.testament, 'Apocrypha') AS testament, COALESCE(g."group", 'Apocrypha') AS "group"
		   FROM book_names n LEFT JOIN books b ON b.book = n.book
		   LEFT JOIN Book g ON g.book_id = n.book AND g.language = 'english'
		   WHERE n.version=? ORDER BY n.book""",
		(version,),
	)]


def _book_meta(con, version, book):
	r = con.execute(
		"SELECT n.name, n.chapters, b.slug, b.name AS english FROM book_names n LEFT JOIN books b ON b.book=n.book WHERE n.version=? AND n.book=?",
		(version, book),
	).fetchone()
	if not r:
		raise LookupError(f"{version} has no book {book}")
	return r


def chapter(con, version, book, chapter, strongs=False):
	v = _version(con, version)
	meta = _book_meta(con, version, book)
	rows = con.execute(
		f"SELECT verse, text, html, para{', raw' if strongs and v['has_strongs'] else ''} FROM verses WHERE version=? AND book=? AND chapter=? ORDER BY verse",
		(version, book, chapter),
	).fetchall()
	if not rows:
		raise LookupError(f"{version} {book}:{chapter} not found")
	return {
		"version": version, "dir": v["dir"], "lang": v["lang"], "book": book, "chapter": chapter,
		"book_name": meta["name"], "english": meta["english"], "slug": meta["slug"], "chapters": meta["chapters"],
		"prev": _neighbour(con, version, book, chapter, -1), "next": _neighbour(con, version, book, chapter, 1),
		"verses": [{k: r[k] for k in r.keys() if r[k] is not None} for r in rows],
	}


def _neighbour(con, version, book, chapter, step):
	if step < 0 and chapter > 1:
		return {"book": book, "chapter": chapter - 1}
	if step > 0 and chapter < _book_meta(con, version, book)["chapters"]:
		return {"book": book, "chapter": chapter + 1}
	r = con.execute(
		f"SELECT book, chapters FROM book_names WHERE version=? AND book {'<' if step < 0 else '>'} ? ORDER BY book {'DESC' if step < 0 else 'ASC'} LIMIT 1",
		(version, book),
	).fetchone()
	if not r:
		return None
	return {"book": r["book"], "chapter": r["chapters"] if step < 0 else 1}


def passage(con, version, book, chapter, start, end=None):
	end = end or start
	return [dict(r) for r in con.execute(
		"SELECT verse, text, html FROM verses WHERE version=? AND book=? AND chapter=? AND verse BETWEEN ? AND ? ORDER BY verse",
		(version, book, chapter, start, end),
	)]


def verse_counts(con, version, book):
	"""Verses per chapter of one book (for the verse wheel)."""
	return [n for (n,) in con.execute(
		"SELECT MAX(verse) FROM verses WHERE version=? AND book=? GROUP BY chapter ORDER BY chapter", (version, book)
	)]


def verse_all(con, book, chapter, verse):
	"""One verse in every version (the app's "Compare versions" sheet)."""
	return [dict(r) for r in con.execute(
		"""SELECT v.version AS code, s.name, s.language, s.lang, s.dir, v.text, v.html
		   FROM verses v JOIN versions s ON s.code = v.version
		   WHERE v.book=? AND v.chapter=? AND v.verse=? ORDER BY s.sort""",
		(book, chapter, verse),
	)]


def compare(con, codes, book, chapter):
	"""Same chapter in several versions, aligned by verse number."""
	out = {"book": book, "chapter": chapter, "versions": []}
	for code in codes[:6]:
		v = _version(con, code)
		rows = con.execute(
			"SELECT verse, text, html FROM verses WHERE version=? AND book=? AND chapter=? ORDER BY verse", (code, book, chapter)
		).fetchall()
		out["versions"].append({
			"code": code, "name": v["name"], "dir": v["dir"], "lang": v["lang"],
			"verses": {r["verse"]: (r["html"] or r["text"]) for r in rows},
		})
	return out


# ------------------------------------------------------------------ search


# Languages whose words take suffixes (அன்பு, அன்பை, அன்பின்…): every word matches as a prefix.
PREFIX_LANGS = {"ta", "ml", "te", "kn", "hi", "bn", "gu", "mr", "or", "pa", "ne", "as", "ur", "fi", "hu", "ko"}
# Searched without vowel points and accents (verses_plain): nobody types them.
PLAIN_LANGS = {"he"}


def strip_marks(s: str) -> str:
	return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _fts_query(q: str, prefix=False) -> str:
	"""User text -> safe FTS5 query: "quoted phrase" kept, other words ANDed, word* prefix allowed."""
	parts = []
	for phrase, word in re.findall(r'"([^"]+)"|(\S+)', q):
		if phrase:
			parts.append('"' + phrase.replace('"', "") + '"')
		elif word:
			star = word.endswith("*")
			w = re.sub(r'["()*:^{}]', "", word)
			if w and w.upper() not in ("AND", "OR", "NOT", "NEAR"):
				parts.append(f'"{w}"' + ("*" if star or prefix else ""))
	return " ".join(parts)


def search(con, q, version, scope="all", page=1, sort="relevance"):
	"""Full-text search in one version. scope: all | ot | nt | <book number>."""
	v = _version(con, version)
	q = (q or "").strip()[:200]
	if not q:
		return {"total": 0, "results": []}
	where, args = ["rowid BETWEEN ? AND ?"], [v["first_id"], v["last_id"]]
	book_clause = ""
	if scope == "ot":
		book_clause = " AND v.book < 40"
	elif scope == "nt":
		book_clause = " AND v.book BETWEEN 40 AND 66"
	elif str(scope).isdigit():
		book_clause = f" AND v.book = {int(scope)}"
	offset = (max(1, int(page)) - 1) * PAGE
	cjk = v["lang"] in ("zh-Hant", "zh-Hans", "zh", "ja")
	plain = v["lang"] in PLAIN_LANGS and "verses_plain" in _tables(con)
	if plain:
		q = strip_marks(q)
	term = q.replace('"', "")

	if cjk and len(term) < 3:  # trigram index needs 3+ characters
		base = f"FROM verses v WHERE v.id BETWEEN ? AND ? AND instr(v.text, ?) > 0{book_clause}"
		total = con.execute(f"SELECT COUNT(*) {base}", (*args, term)).fetchone()[0]
		rows = con.execute(
			f"SELECT v.book, v.chapter, v.verse, replace(v.text, ?, '<mark>' || ? || '</mark>') AS hit {base} ORDER BY v.id LIMIT {PAGE} OFFSET {offset}",
			(term, term, *args, term),
		).fetchall()
	else:
		table = "verses_tri" if cjk else "verses_plain" if plain else "verses_fts"
		match = f'"{term}"' if cjk else _fts_query(q, prefix=v["lang"] in PREFIX_LANGS)
		if not match:
			return {"total": 0, "results": []}
		base = f"FROM {table} f JOIN verses v ON v.id = f.rowid WHERE {table} MATCH ? AND f.{' AND f.'.join(where)}{book_clause}"
		total = con.execute(f"SELECT COUNT(*) {base}", (match, *args)).fetchone()[0]
		# Relevance, like a search engine: verses containing the words as one exact phrase first, then
		# FTS5's bm25 score (where the words weigh most), then Bible order. sort="bible" keeps Bible order.
		phrase = re.sub(r'["*]', "", q).strip().lower()
		order = "v.id" if sort == "bible" or cjk else (
			"CASE WHEN instr(lower(v.text), ?) > 0 THEN 0 ELSE 1 END, bm25(" + table + "), v.id")
		rows = con.execute(
			f"SELECT v.book, v.chapter, v.verse, highlight({table}, 0, '<mark>', '</mark>') AS hit{', v.text AS pointed' if plain else ''} {base} ORDER BY {order} LIMIT {PAGE} OFFSET {offset}",
			(match, *args) if order == "v.id" else (match, *args, phrase),
		).fetchall()

	names = {r["book"]: r["name"] for r in con.execute("SELECT book, name FROM book_names WHERE version=?", (version,))}
	return {
		"total": total, "page": int(page), "pages": (total + PAGE - 1) // PAGE,
		"results": [_repoint({**dict(r), "book_name": names.get(r["book"])}) for r in rows],
	}


def _repoint(r):
	"""A Hebrew hit was found in the text without points: put its marks back on the pointed words."""
	pointed = r.pop("pointed", None)
	if pointed:
		words, hits = pointed.split(" "), r["hit"].split(" ")
		if len(words) == len(hits):
			r["hit"] = " ".join(f"<mark>{w}</mark>" if "<mark>" in h else w for w, h in zip(words, hits))
	return r


# ------------------------------------------------------------------ references


@lru_cache(maxsize=1)
def _abbrevs(con):
	"""Abbreviation/name -> book, from the study data's e-Sword abbreviations plus English names and OSIS ids."""
	m = {}
	for b, abbrev in con.execute("SELECT book_id, abbrev FROM Book WHERE book_id <= 66"):
		if abbrev:
			m[abbrev.lower().replace(" ", "")] = b
	for b, osis, slug, name in con.execute("SELECT book, osis, slug, name FROM books"):
		for k in (osis, slug, name, name.replace(" ", "")):
			m[k.lower().replace(" ", "").replace("-", "")] = b
	for b, name in con.execute("SELECT book_id, book_name FROM Book WHERE book_id <= 66"):  # English + Tamil names
		if name:
			m[name.strip().lower().replace(" ", "")] = b
	m.update({"psalm": 19, "song": 22, "songofsongs": 22, "joh": 43, "jn": 43, "ro": 45, "php": 50, "phm": 57})
	return m


_REF = re.compile(r"((?:[1-3]\s?)?[^\W\d_][^\d:]*?)\.?\s*(\d+)(?:[:.](\d+)(?:[-–](\d+))?)?")


def parse_refs(con, text):
	"""'Ex 6:16-20; Jos 21:4; 10; 1Ch 6:2' -> list of {book, chapter, verse, end}. A bare number after
	a verse continues the same book and chapter (e-Sword style)."""
	ab = _abbrevs(con)
	out, book, chap = [], None, None
	for part in re.split(r"[;,]", text or ""):
		part = part.strip()
		if not part:
			continue
		m = _REF.fullmatch(part)
		if m:
			b = ab.get(m.group(1).lower().replace(" ", "").replace(".", ""))
			if not b:
				continue
			book, chap = b, int(m.group(2))
			verse = int(m.group(3)) if m.group(3) else None
			end = int(m.group(4)) if m.group(4) else None
		elif book and re.fullmatch(r"(\d+)(?::(\d+))?(?:[-–](\d+))?", part):
			n = re.fullmatch(r"(\d+)(?::(\d+))?(?:[-–](\d+))?", part)
			if n.group(2):
				chap, verse, end = int(n.group(1)), int(n.group(2)), int(n.group(3)) if n.group(3) else None
			else:
				verse, end = int(n.group(1)), int(n.group(3)) if n.group(3) else None
		else:
			continue
		out.append({"book": book, "chapter": chap, "verse": verse, "end": end})
	return out


def _with_text(con, refs, version):
	out = []
	for r in refs:
		start = r.get("verse") or 1
		end = r.get("end") or start
		rows = con.execute(
			"SELECT text FROM verses WHERE version=? AND book=? AND chapter=? AND verse BETWEEN ? AND ? ORDER BY verse LIMIT 3",
			(version, r["book"], r["chapter"], start, min(end, start + 2)),
		).fetchall()
		out.append({**r, "text": " ".join(x[0] for x in rows)})
	return out


def cross_references(con, book, chapter, verse, version="KJV", limit=60):
	refs = [
		{"book": r[0], "chapter": r[1], "verse": r[2], "end": r[3] if r[3] != r[2] else None}
		for r in con.execute(
			"SELECT to_book, to_chapter, to_verse_start, to_verse_end FROM cross_references WHERE from_book=? AND from_chapter=? AND from_verse=? ORDER BY id LIMIT ?",
			(book, chapter, verse, limit),
		)
	]
	return _with_text(con, refs, version)


def tsk(con, book, chapter, verse):
	r = con.execute("SELECT content, content_html FROM tsk_entries WHERE book_id=? AND chapter=? AND verse=?", (book, chapter, verse)).fetchone()
	if not r:
		return None
	refs = re.findall(r'passage="([^"]+)"', r["content_html"] or "")
	return {"html": r["content_html"], "text": r["content"], "refs": [x for p in refs for x in parse_refs(con, p)]}


def commentary(con, book, chapter):
	return [dict(r) for r in con.execute(
		"SELECT fromverse, toverse, data FROM mh_commentary WHERE book=? AND chapter=? ORDER BY fromverse", (book, chapter)
	)]


def strongs(con, code):
	code = (code or "").upper().strip()
	r = con.execute("SELECT word, data FROM dictionary WHERE word=?", (code,)).fetchone()
	return dict(r) if r else None


def dictionary(con, word):
	r = con.execute("SELECT word, data FROM easton_dictionary WHERE word=? COLLATE NOCASE", ((word or "").strip(),)).fetchone()
	return dict(r) if r else None


def topics(con, q, limit=40):
	q = _fts_query(q)
	if not q:
		return []
	return [dict(r) for r in con.execute(
		"SELECT title, source, topic_id FROM topics_fts WHERE topics_fts MATCH ? ORDER BY rank LIMIT ?", (q + "*" if not q.endswith("*") else q, limit)
	)]


def topic(con, source, topic_id):
	if source == "nave":
		t = con.execute("SELECT title FROM nave_topics WHERE id=?", (topic_id,)).fetchone()
		subs = con.execute("SELECT label, scripture_refs FROM nave_subTopics WHERE topic_id=? ORDER BY id", (topic_id,)).fetchall()
	else:
		t = con.execute("SELECT title FROM torrey_topics WHERE id=?", (topic_id,)).fetchone()
		subs = con.execute("SELECT label, scripture_refs FROM torrey_subtopics WHERE topic_id=? ORDER BY id", (topic_id,)).fetchall()
	if not t:
		return None
	return {
		"title": t[0], "source": source,
		"entries": [{"label": s[0], "refs": parse_refs(con, s[1]), "text": s[1]} for s in subs],
	}


def devotional(con, month, day):
	return [dict(r) for r in con.execute(
		"SELECT session_type, title, verse_text, bible_reference, content FROM devotional_entries WHERE month=? AND day=? ORDER BY session_type DESC",
		(month, day),
	)]


# ------------------------------------------------------------------ unified search (like the app's search bar)

try:  # package import inside Frappe; plain import when run from this folder (tools, benchmarks)
	from . import rank as R  # noqa: E402
	from . import translit as T  # noqa: E402
except ImportError:
	import rank as R  # noqa: E402
	import translit as T  # noqa: E402

_DOCS = {}


def _local_docs(con):
	"""Rankable docs from the database (built once per connection): books, topics, dictionary words."""
	key = id(con)
	if key not in _DOCS:
		docs = []
		tamil = dict(con.execute("SELECT book_id, trim(book_name) FROM Book WHERE language='tamil'"))
		group = dict(con.execute("SELECT book_id, \"group\" FROM Book WHERE language='english'"))
		for b, slug, name, chapters in con.execute("SELECT book, slug, name, chapters FROM books"):
			docs.append(R.Doc("Books", name, f"{chapters} chapters · {group.get(b, '')}", [tamil.get(b, ""), slug],
				{"book": b, "slug": slug}))
		for tid, title in con.execute("SELECT id, title FROM nave_topics"):
			docs.append(R.Doc("Topics", title.title(), "Nave's Topical Bible", (), {"source": "nave", "id": tid}))
		for tid, title in con.execute("SELECT id, title FROM torrey_topics"):
			docs.append(R.Doc("Topics", title.title(), "Torrey's Topical Textbook", (), {"source": "torrey", "id": tid}))
		for (word,) in con.execute("SELECT word FROM easton_dictionary"):
			docs.append(R.Doc("Dictionary", word, "Easton's Bible Dictionary", (), {"word": word}))
		_DOCS.clear()
		_DOCS[key] = docs
	return _DOCS[key]


def _fts_rows(con, sql, match, limit):
	try:
		return con.execute(sql, (match, limit)).fetchall()
	except sqlite3.OperationalError:  # e.g. a query made only of punctuation
		return []


_VOCAB = {}


@lru_cache(maxsize=8)
def _tables(con):
	return {n for (n,) in con.execute("SELECT name FROM sqlite_master")}


def _vocab(con, lang):
	"""Words of one language's Bibles: the database's vocab table, or (older databases) built in memory."""
	if "vocab" in _tables(con):
		return T.SqlVocab(con, lang)
	key = (id(con), lang)
	if key not in _VOCAB:
		letters = re.compile(T.SCRIPTS[lang].letters)
		counts = {}
		for (text,) in con.execute("SELECT v.text FROM verses v JOIN versions x ON x.code = v.version WHERE x.lang = ?", (lang,)):
			for w in letters.findall(text):
				counts[w] = counts.get(w, 0) + 1
		_VOCAB[key] = T.Vocab(counts)
	return _VOCAB[key]


@lru_cache(maxsize=8)
def _indian(con):
	"""Indian languages with a Bible here -> the version to search in each (the first in the list)."""
	out = {}
	for code, lang in con.execute("SELECT code, lang FROM versions ORDER BY sort"):
		if lang in T.SCRIPTS and lang not in out:
			out[lang] = code
	return out


# Which language leads when English letters spell real words in several (prem: Hindi, Nepali, Marathi…):
# the site's own Tamil readers and Hindi, the widest-read, weigh double.
LANG_WEIGHT = {"ta": 2.0, "hi": 2.0}


def _langs(con, version, lang=""):
	"""Which languages English letters may stand for: the version's own, a preferred one, then the rest."""
	v = _version(con, version) if version else None
	if v and v["lang"] in T.SCRIPTS:
		return [v["lang"]]
	langs = list(_indian(con))
	if lang in langs:
		langs.remove(lang)
		langs.insert(0, lang)
	return langs


def romanized(con, q, lang):
	"""An Indian language typed in English letters, in its own script ("anbu" -> "அன்பு"), or None."""
	if not T.is_tanglish(q) or len(q.split()) > 6 or lang not in T.SCRIPTS:
		return None
	words = []
	for w in q.split():
		found = T.transliterate(w, _vocab(con, lang), T.SCRIPTS[lang], limit=1)
		if not found:
			return None
		words.append(found[0])
	return " ".join(words)


def tanglish(con, q):
	return romanized(con, q, "ta")


def native_suggest(con, q, version="", lang="", limit=6):
	"""Words for the last word being typed in English letters, in the likeliest Indian language, with the
	earlier words kept: "yesu anb" -> [{"word": "அன்பு", "query": "yesu அன்பு", "lang": "ta"}, ...]."""
	q = (q or "").strip()[:120]
	if not q or not T.is_tanglish(q):
		return []
	*head, last = q.split()
	best, best_score = None, 0
	for i, lg in enumerate(_langs(con, version, lang)):
		vocab = _vocab(con, lg)
		words = T.suggest(last, vocab, limit, T.SCRIPTS[lg])
		if not words:
			continue
		if i == 0 and lg == lang:  # the language the reader picked last time wins while it has words
			best = (lg, words)
			break
		score = vocab.count(words[0]) / _tokens(con, lg) * LANG_WEIGHT.get(lg, 1)
		if score > best_score:
			best, best_score = (lg, words), score
	if not best:
		return []
	lg, words = best
	return [{"word": w, "query": " ".join(head + [w]), "lang": lg, "language": T.SCRIPTS[lg].language} for w in words]


def tamil_suggest(con, q, limit=6):
	return native_suggest(con, q, lang="ta", limit=limit)


@lru_cache(maxsize=32)
def _tokens(con, lang):
	if "vocab" in _tables(con):
		return con.execute("SELECT sum(n) FROM vocab WHERE lang=?", (lang,)).fetchone()[0] or 1
	return sum(_vocab(con, lang).counts.values()) or 1


def unified(con, q, version="KJV", entities=None, per_group=6, native_lang=""):
	"""Everything that matches q, grouped like the app: a reference to jump to, ranked entities
	(books, topics, dictionary, plus characters/places/events/themes passed in by the caller),
	Strong's, commentary, devotionals and the best verses. `entities` is {type: [Doc, ...]}."""
	q = (q or "").strip()[:120]
	out = {"query": q, "reference": None, "groups": [], "verses": {"total": 0, "results": []}, "did_you_mean": None}
	if not q:
		return out
	v = _version(con, version)

	refs = parse_refs(con, q) if re.search(r"\d", q) else []
	if refs and re.fullmatch(r"\s*\S.*?\s*\d+([:.]\d+([-–]\d+)?)?\s*", q):
		r = refs[0]
		names = dict(con.execute("SELECT book, name FROM book_names WHERE version=?", (version,)))
		if r["book"] in names:
			out["reference"] = {**r, "label": f"{names[r['book']]} {r['chapter']}" + (f":{r['verse']}" + (f"–{r['end']}" if r.get("end") else "") if r.get("verse") else ""),
				"preview": " ".join(x["text"] for x in passage(con, version, r["book"], r["chapter"], r.get("verse") or 1, (r.get("end") or r.get("verse") or 3)))[:400]}

	docs = list(_local_docs(con))
	for typ, items in (entities or {}).items():
		docs.extend(items)
	ranked = R.search(docs, q, limit=400)
	order = ["Books", "Characters", "Places", "Events", "Themes", "Topics", "Dictionary"]
	grouped = {}
	for score, d in ranked:
		grouped.setdefault(d.type, [])
		if len(grouped[d.type]) < per_group:
			grouped[d.type].append({"title": d.title, "subtitle": d.subtitle, "score": round(score, 1), **(d.data or {})})
	totals = {}
	for _, d in ranked:
		totals[d.type] = totals.get(d.type, 0) + 1
	for typ in order + [t for t in grouped if t not in order]:
		if typ in grouped:
			out["groups"].append({"type": typ, "total": totals[typ], "items": grouped[typ]})

	# Strong's: by number (G26, H7225) or by meaning / original word.
	code = q.upper().replace(" ", "")
	if re.fullmatch(r"[HG]\d{1,5}", code):
		s = strongs(con, code)
		strongs_items = [{"code": code, "title": code, "subtitle": R.normalize(re.sub("<[^>]+>", " ", s["data"]))[:140] if s else ""}] if s else []
	else:
		match = _fts_query(q)
		strongs_items = [
			{"code": c, "title": f"{o} ({t})" if o else c, "subtitle": f"{c} · " + d[:140]}
			for c, o, t, d in _fts_rows(con, "SELECT code, original, translit, definition FROM strongs_fts WHERE strongs_fts MATCH ? ORDER BY bm25(strongs_fts, 0, 8, 8, 1) LIMIT ?", match, 5)
		] if match else []
	if strongs_items:
		out["groups"].append({"type": "Word study", "total": len(strongs_items), "items": strongs_items})

	match = _fts_query(q)
	if match:
		bnames = dict(con.execute("SELECT book, name FROM books"))
		com = _fts_rows(con, "SELECT book, chapter, fromverse, toverse, snippet(commentary_fts, 0, '<mark>', '</mark>', '…', 18) FROM commentary_fts WHERE commentary_fts MATCH ? ORDER BY rank LIMIT ?", match, 5)
		if com:
			out["groups"].append({"type": "Commentary", "total": len(com), "items": [
				{"title": f"{bnames.get(b, b)} {c}:{f}" + (f"–{t}" if t and t != f else ""), "subtitle": "Matthew Henry", "snippet": s, "book": b, "chapter": c, "verse": f}
				for b, c, f, t, s in com]})
		dev = _fts_rows(con, "SELECT title, reference, month, day, session, snippet(devotional_fts, 3, '<mark>', '</mark>', '…', 16) FROM devotional_fts WHERE devotional_fts MATCH ? ORDER BY rank LIMIT ?", match, 4)
		if dev:
			out["groups"].append({"type": "Devotionals", "total": len(dev), "items": [
				{"title": t, "subtitle": f"Spurgeon · {r}", "snippet": s, "month": m, "day": d, "session": se} for t, r, m, d, se, s in dev]})

	if not out["reference"]:
		v_res = search(con, q, version)
		out["verses"] = {"total": v_res["total"], "results": v_res["results"][:8]}
		# Few hits for English letters: perhaps an Indian language typed in English ("anbu", "prem"), so
		# search those Bibles too; the language with the most verses leads, the others are offered.
		if v_res["total"] < 3 and T.is_tanglish(q):
			found = []
			for lang in _langs(con, version, native_lang):
				nq = romanized(con, q, lang)
				if not nq:
					continue
				nv = version if v["lang"] == lang else _indian(con)[lang]
				res = search(con, nq, nv)
				if res["total"] == 0:  # the best spelling may be a word's beginning: தாவீத -> தாவீது
					res = search(con, nq + "*", nv)
				if res["total"]:
					found.append({"query": nq, "version": nv, "lang": lang, "language": T.SCRIPTS[lang].language, "total": res["total"], "results": res["results"][:8]})
			if found:
				found.sort(key=lambda f: (f["lang"] != native_lang, -f["total"] * LANG_WEIGHT.get(f["lang"], 1)))
				out["native"] = found[0]
				out["native_more"] = [{k: f[k] for k in ("query", "version", "lang", "language", "total")} for f in found[1:6]]
	strong = any(g["type"] in ("Word study", "Commentary", "Devotionals") or g["items"][0].get("score", 0) >= 16 for g in out["groups"])
	if not out["verses"]["total"] and not out["reference"] and not strong and not out.get("native"):
		out["did_you_mean"] = R.suggest(docs, q)
	return out
