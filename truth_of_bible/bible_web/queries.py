"""Read-only queries over tob_bible_web.db (see build.py). Plain sqlite3, no Frappe — the API in
truth_of_bible/api/bible_web.py is a thin wrapper, and these can be tested or timed on their own."""

import re
import sqlite3
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
PREFIX_LANGS = {"ta", "ml", "te", "kn", "hi", "bn", "gu", "mr", "or", "pa", "ne", "fi", "hu"}


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
	term = q.replace('"', "")

	if cjk and len(term) < 3:  # trigram index needs 3+ characters
		base = f"FROM verses v WHERE v.id BETWEEN ? AND ? AND instr(v.text, ?) > 0{book_clause}"
		total = con.execute(f"SELECT COUNT(*) {base}", (*args, term)).fetchone()[0]
		rows = con.execute(
			f"SELECT v.book, v.chapter, v.verse, replace(v.text, ?, '<mark>' || ? || '</mark>') AS hit {base} ORDER BY v.id LIMIT {PAGE} OFFSET {offset}",
			(term, term, *args, term),
		).fetchall()
	else:
		table = "verses_tri" if cjk else "verses_fts"
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
			f"SELECT v.book, v.chapter, v.verse, highlight({table}, 0, '<mark>', '</mark>') AS hit {base} ORDER BY {order} LIMIT {PAGE} OFFSET {offset}",
			(match, *args) if order == "v.id" else (match, *args, phrase),
		).fetchall()

	names = {r["book"]: r["name"] for r in con.execute("SELECT book, name FROM book_names WHERE version=?", (version,))}
	return {
		"total": total, "page": int(page), "pages": (total + PAGE - 1) // PAGE,
		"results": [{**dict(r), "book_name": names.get(r["book"])} for r in rows],
	}


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
except ImportError:
	import rank as R  # noqa: E402

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


def unified(con, q, version="KJV", entities=None, per_group=6):
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
	strong = any(g["type"] in ("Word study", "Commentary", "Devotionals") or g["items"][0].get("score", 0) >= 16 for g in out["groups"])
	if not out["verses"]["total"] and not out["reference"] and not strong:
		out["did_you_mean"] = R.suggest(docs, q)
	return out
