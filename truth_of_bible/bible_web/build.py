"""Builds the read-only Bible database behind truthofbible.org's web Bible (tob_bible_web.db).

Inputs are the same files the app downloads: one SQLite module per version (zip or .db, named
<code>.zip / <code>.db) and the bundled study database (bible_tamil.db: cross references, TSK,
Matthew Henry, Strong's/Easton, Nave/Torrey, Spurgeon, gospel harmony). Only versions with
web=true in catalogue.json are included.

Book numbers differ between modules (Apocrypha inserted before Matthew, Catholic/Orthodox order,
Tanakh order), so books are mapped to the 66-book Protestant numbering by their chapter/verse
structure, not by id. Books with no match (Apocrypha) keep ids from 101 up in their own version.

    python build.py --modules DIR --out tob_bible_web.db --download [--study bible_tamil.db]

No Frappe needed; run it anywhere with Python 3.10+.
"""

import argparse
import html as htmlmod
import io
import json
import re
import sqlite3
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOGUE_URL = "https://truthofbible.org/wp-content/uploads/bible/databases.json"
STUDY_URL = "https://media.truthofbible.org/bible/study/bible_tamil.db.zip"  # same file the app bundles

# (osis, url slug, English name) for books 1–66.
BOOKS = [
	("Gen", "genesis", "Genesis"), ("Exod", "exodus", "Exodus"), ("Lev", "leviticus", "Leviticus"),
	("Num", "numbers", "Numbers"), ("Deut", "deuteronomy", "Deuteronomy"), ("Josh", "joshua", "Joshua"),
	("Judg", "judges", "Judges"), ("Ruth", "ruth", "Ruth"), ("1Sam", "1-samuel", "1 Samuel"),
	("2Sam", "2-samuel", "2 Samuel"), ("1Kgs", "1-kings", "1 Kings"), ("2Kgs", "2-kings", "2 Kings"),
	("1Chr", "1-chronicles", "1 Chronicles"), ("2Chr", "2-chronicles", "2 Chronicles"), ("Ezra", "ezra", "Ezra"),
	("Neh", "nehemiah", "Nehemiah"), ("Esth", "esther", "Esther"), ("Job", "job", "Job"),
	("Ps", "psalms", "Psalms"), ("Prov", "proverbs", "Proverbs"), ("Eccl", "ecclesiastes", "Ecclesiastes"),
	("Song", "song-of-solomon", "Song of Solomon"), ("Isa", "isaiah", "Isaiah"), ("Jer", "jeremiah", "Jeremiah"),
	("Lam", "lamentations", "Lamentations"), ("Ezek", "ezekiel", "Ezekiel"), ("Dan", "daniel", "Daniel"),
	("Hos", "hosea", "Hosea"), ("Joel", "joel", "Joel"), ("Amos", "amos", "Amos"), ("Obad", "obadiah", "Obadiah"),
	("Jonah", "jonah", "Jonah"), ("Mic", "micah", "Micah"), ("Nah", "nahum", "Nahum"), ("Hab", "habakkuk", "Habakkuk"),
	("Zeph", "zephaniah", "Zephaniah"), ("Hag", "haggai", "Haggai"), ("Zech", "zechariah", "Zechariah"),
	("Mal", "malachi", "Malachi"), ("Matt", "matthew", "Matthew"), ("Mark", "mark", "Mark"), ("Luke", "luke", "Luke"),
	("John", "john", "John"), ("Acts", "acts", "Acts"), ("Rom", "romans", "Romans"),
	("1Cor", "1-corinthians", "1 Corinthians"), ("2Cor", "2-corinthians", "2 Corinthians"),
	("Gal", "galatians", "Galatians"), ("Eph", "ephesians", "Ephesians"), ("Phil", "philippians", "Philippians"),
	("Col", "colossians", "Colossians"), ("1Thess", "1-thessalonians", "1 Thessalonians"),
	("2Thess", "2-thessalonians", "2 Thessalonians"), ("1Tim", "1-timothy", "1 Timothy"),
	("2Tim", "2-timothy", "2 Timothy"), ("Titus", "titus", "Titus"), ("Phlm", "philemon", "Philemon"),
	("Heb", "hebrews", "Hebrews"), ("Jas", "james", "James"), ("1Pet", "1-peter", "1 Peter"),
	("2Pet", "2-peter", "2 Peter"), ("1John", "1-john", "1 John"), ("2John", "2-john", "2 John"),
	("3John", "3-john", "3 John"), ("Jude", "jude", "Jude"), ("Rev", "revelation", "Revelation"),
]

# Languages written without spaces between words get a trigram index instead of word tokens.
CJK = {"zh-Hant", "zh-Hans", "zh", "ja"}
_CJK_GAP = re.compile(r"(?<=[　-鿿＀-￯])\s+(?=[　-鿿＀-￯])")

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE versions(code TEXT PRIMARY KEY, name TEXT, language TEXT, lang TEXT, dir TEXT, license TEXT,
	attribution TEXT, note TEXT, has_strongs INT, verse_count INT, first_id INT, last_id INT, sort INT);
CREATE TABLE books(book INT PRIMARY KEY, osis TEXT, slug TEXT UNIQUE, name TEXT, testament TEXT, chapters INT);
CREATE TABLE book_names(version TEXT, book INT, name TEXT, chapters INT, PRIMARY KEY(version, book));
CREATE TABLE verses(id INTEGER PRIMARY KEY, version TEXT, book INT, chapter INT, verse INT,
	text TEXT, html TEXT, raw TEXT, para INT);
"""

_TAG = re.compile(r"</?[A-Za-z][^<>]*>")  # real tags only: "a < b" stays text


def clean(text: str) -> tuple[str, str | None, int]:
	"""Module markup -> (plain text, light HTML or None when same as text, starts-paragraph flag)."""
	t = text or ""
	para = 1 if "<pb/>" in t else 0
	t = re.sub(r"<RF>.*?<Rf>|<f>.*?</f>|<TS>.*?<Ts>|<n>.*?</n>", "", t, flags=re.S)  # footnotes, headings
	t = re.sub(r"<W[HGT][^>]*>|<XW[^>]*>", "", t)  # Strong's / morphology (kept in `raw`)
	h = htmlmod.escape(_TAG.sub(lambda m: f"\0{m.group(0)}\0", t), quote=False)
	# Restore the few tags that carry meaning for reading.
	repl = {
		"<FR>": '<span class="j">', "<Fr>": "</span>", "<J>": '<span class="j">', "</J>": "</span>",
		"<FI>": "<i>", "<Fi>": "</i>", "<e>": '<span class="t">', "</e>": "</span>",
		"<t>": '<span class="l">', "</t>": "</span>",
	}

	def tag(m):
		raw = htmlmod.unescape(m.group(1))
		if raw.startswith("<title"):
			return '<span class="t">'
		if raw == "</title>":
			return "</span>"
		return repl.get(raw, "")

	h = re.sub(r"\0(.*?)\0", tag, h).strip()
	h = re.sub(r"\s+", " ", h)
	for open_, close in (('<span', '</span>'), ('<i>', '</i>')):  # close what a verse leaves open
		h += close * max(0, h.count(open_) - h.count(close))
	plain = re.sub(r"\s+", " ", htmlmod.unescape(_TAG.sub("", h))).strip()
	return plain, (h if h != htmlmod.escape(plain, quote=False) else None), para


def find_module(modules: Path, code: str) -> Path | None:
	"""<code>.db or <code>.zip anywhere under `modules` (the server mirror keeps global/ and indian/)."""
	for pattern in (f"{code}.db", f"{code}.zip"):
		hit = next(iter(sorted(modules.rglob(pattern))), None)
		if hit:
			return hit
	return None


def open_module(path: Path) -> sqlite3.Connection:
	if path.suffix == ".zip":
		z = zipfile.ZipFile(path)
		name = next(n for n in z.namelist() if not n.endswith("/"))
		# Unzip into a private cache, never next to the zip (the server mirror folder is public).
		cache = Path(tempfile.gettempdir()) / "tob_bible_modules"
		cache.mkdir(exist_ok=True)
		dest = cache / (path.stem + ".db")
		if not dest.exists() or dest.stat().st_mtime < path.stat().st_mtime:
			dest.write_bytes(z.read(name))
		path = dest
	return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def shape(con, table, book):
	return [n for (n,) in con.execute(f"SELECT COUNT(*) FROM {table} WHERE book_id=? GROUP BY chapter ORDER BY chapter", (book,))]


_ROMAN = {"I": "1", "II": "2", "III": "3", "IV": "4"}
_ALIASES = {"revelation of john": "revelation", "song of songs": "song of solomon", "psalm": "psalms"}
_CANON = {name.lower(): b for b, (_, _, name) in enumerate(BOOKS, 1)}


def canon_by_name(name: str) -> int | None:
	"""Global modules name books in English ("I Samuel", "Revelation of John")."""
	n = (name or "").strip()
	first, _, rest = n.partition(" ")
	if first in _ROMAN and rest:
		n = f"{_ROMAN[first]} {rest}"
	n = n.lower()
	return _CANON.get(_ALIASES.get(n, n))


def map_books(con, table, ref, names):
	"""version book_id -> canonical 1..66. English names first, then chapter/verse structure plus
	order, then a single remaining gap between two mapped neighbours is filled by position."""
	ids = [b for (b,) in con.execute(f"SELECT DISTINCT book_id FROM {table} ORDER BY book_id")]
	shapes = {b: shape(con, table, b) for b in ids}
	out = {}
	for b in ids:
		c = canon_by_name(names.get(b, ""))
		if c and c not in out.values():
			out[b] = c
	pairs = []
	for i, b in enumerate(ids):
		if b in out:
			continue
		vs = shapes[b]
		for c, rs in ref.items():
			n = min(len(vs), len(rs))
			diff = abs(len(vs) - len(rs)) * 12 + sum(abs(x - y) for x, y in zip(vs[:n], rs[:n]))
			score = diff / max(1, sum(rs)) + abs(i / len(ids) - (c - 1) / 66) * 0.15
			pairs.append((score, b, c))
	used_b, used_c = set(out), set(out.values())
	for score, b, c in sorted(pairs):
		if b in used_b or c in used_c or score > 0.35:
			continue
		out[b] = c
		used_b.add(b)
		used_c.add(c)
	# Gap fill: e.g. Joel/Malachi with Hebrew chapter division in a module with native book names.
	for i, b in enumerate(ids):
		if b in out or i == 0 or i == len(ids) - 1:
			continue
		prev, nxt = out.get(ids[i - 1]), out.get(ids[i + 1])
		if prev and nxt and nxt - prev == 2 and prev + 1 not in out.values():
			out[b] = prev + 1
	return ids, out


def download(modules: Path, codes):
	cat = json.load(urllib.request.urlopen(CATALOGUE_URL, timeout=60))
	urls = {x["id"]: x["download"] for x in cat}
	for code in codes:
		dest = modules / f"{code}.zip"
		if not find_module(modules, code) and code in urls:
			print("download", code)
			dest.write_bytes(urllib.request.urlopen(urls[code], timeout=600).read())


def _text(h: str) -> str:
	return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", h or ""))).strip()


def index_study(db):
	"""Full-text indexes behind the unified search: commentary, Easton, Strong's, devotionals."""
	tok = "tokenize=\"unicode61 remove_diacritics 2\""
	db.executescript(f"""
		CREATE VIRTUAL TABLE commentary_fts USING fts5(text, book UNINDEXED, chapter UNINDEXED, fromverse UNINDEXED, toverse UNINDEXED, {tok});
		CREATE VIRTUAL TABLE easton_fts USING fts5(word, text, {tok});
		CREATE VIRTUAL TABLE strongs_fts USING fts5(code UNINDEXED, original, translit, definition, {tok});
		CREATE VIRTUAL TABLE devotional_fts USING fts5(title, verse_text, reference, content, month UNINDEXED, day UNINDEXED, session UNINDEXED, {tok});
	""")
	db.executemany(
		"INSERT INTO commentary_fts VALUES (?,?,?,?,?)",
		((_text(d), b, c, f, t) for b, c, f, t, d in db.execute("SELECT book, chapter, fromverse, toverse, data FROM mh_commentary WHERE chapter > 0").fetchall()),
	)
	db.execute("INSERT INTO easton_fts SELECT word, data FROM easton_dictionary")
	rows = []
	for code, data in db.execute("SELECT word, data FROM dictionary WHERE word GLOB '[HG][0-9]*'").fetchall():
		orig = re.search(r"Original:\s*<strong>(.*?)</strong>", data or "")
		tr = re.search(r"Transliteration:\s*<strong>(.*?)</strong>", data or "")
		rows.append((code, _text(orig.group(1)) if orig else "", _text(tr.group(1)) if tr else "", _text(data)))
	db.executemany("INSERT INTO strongs_fts VALUES (?,?,?,?)", rows)
	db.execute(
		"INSERT INTO devotional_fts SELECT title, verse_text, bible_reference, content, month, day, session_type FROM devotional_entries"
	)
	db.commit()


def build(modules: Path, study: Path, out: Path, do_download=False):
	t0 = time.time()
	catalogue = [v for v in json.loads((HERE / "catalogue.json").read_text(encoding="utf-8"))["versions"] if v["web"]]
	if do_download:
		download(modules, [v["code"] for v in catalogue])
	if str(study).startswith("http"):
		dest = modules / Path(str(study)).name
		if not dest.exists():
			dest.write_bytes(urllib.request.urlopen(str(study), timeout=600).read())
		study = dest
	sdb = open_module(Path(study))
	# The app's own Tamil book names: module names are abbreviated (IRV "யோவா") or carry stray markup.
	tamil_names = {b: n.strip() for b, n in sdb.execute("SELECT book_id, book_name FROM Book WHERE language='tamil'")}

	tmp = out.with_suffix(".building")
	tmp.unlink(missing_ok=True)
	db = sqlite3.connect(tmp)
	db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + SCHEMA)

	kjv = open_module(find_module(modules, "KJV"))
	ref = {b: shape(kjv, "KJV_verses", b) for b in range(1, 67)}
	for b, (osis, slug, name) in enumerate(BOOKS, 1):
		db.execute("INSERT INTO books VALUES (?,?,?,?,?,?)", (b, osis, slug, name, "OT" if b < 40 else "NT", len(ref[b])))

	next_id = 1
	for sort, v in enumerate(catalogue):
		code = v["code"]
		src = find_module(modules, code)
		if not src:
			print(f"  !! {code}: module not found, skipped")
			continue
		con = open_module(src)
		table = f"{code}_verses"
		names = {b: (n or "").strip() for b, n in con.execute(f"SELECT id, name FROM {code}_books")}
		ids, mapping = map_books(con, table, ref, names)
		extra = 101
		for b in ids:
			if b not in mapping:
				mapping[b] = extra
				extra += 1
		first = next_id
		rows = []
		has_strongs = 0
		para_next = 0  # KJV-style modules end a paragraph with <CM>
		for book, chapter, verse, text in con.execute(f"SELECT book_id, chapter, verse, text FROM {table} ORDER BY book_id, chapter, verse"):
			if not text or not text.strip():
				continue
			plain, html, para = clean(text)
			if v["lang"] in CJK:  # these modules space-separate words; Chinese/Japanese text has no spaces
				plain = _CJK_GAP.sub("", plain)
				html = _CJK_GAP.sub("", html) if html else None
			para, para_next = para or para_next, int("<CM>" in text)
			if not plain:
				continue
			raw = text if "<W" in text else None
			has_strongs |= raw is not None
			rows.append((next_id, code, mapping[book], chapter, verse, plain, html, raw, para))
			next_id += 1
		db.executemany("INSERT INTO verses VALUES (?,?,?,?,?,?,?,?,?)", rows)
		for b in ids:
			chapters = len(shape(con, table, b))
			name = names.get(b) or ""
			if v["lang"] == "ta" and mapping[b] in tamil_names:
				name = tamil_names[mapping[b]]
			elif mapping[b] <= 66 and (not name or canon_by_name(name)):
				name = BOOKS[mapping[b] - 1][2]  # English-named module: use the standard spelling
			db.execute("INSERT INTO book_names VALUES (?,?,?,?)", (code, mapping[b], name or f"Book {b}", chapters))
		db.execute(
			"INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
			(code, v["name"], v["language"], v["lang"], v["dir"], v["license"], v.get("attribution"), v.get("note"),
			 has_strongs, len(rows), first, next_id - 1, sort),
		)
		unmatched = [b for b in ids if mapping[b] > 100]
		print(f"  {code:15} {len(rows):6} verses, {len(ids)} books" + (f", {len(unmatched)} extra (Apocrypha)" if unmatched else ""))
		db.commit()

	print("indexing verses…")
	db.executescript("""
		CREATE INDEX verses_ref ON verses(version, book, chapter, verse);
		CREATE INDEX verses_xref ON verses(book, chapter, verse);
	""")
	cjk = [r[0] for r in db.execute(f"SELECT code FROM versions WHERE lang IN ({','.join('?' * len(CJK))})", tuple(CJK))]
	db.executescript("""
		CREATE VIRTUAL TABLE verses_fts USING fts5(text, content='verses', content_rowid='id',
			tokenize="unicode61 remove_diacritics 2 categories 'L* N* Co M*'");
		CREATE VIRTUAL TABLE verses_tri USING fts5(text, content='verses', content_rowid='id', tokenize='trigram');
	""")
	q = ",".join("?" * len(cjk)) or "''"
	db.execute(f"INSERT INTO verses_fts(rowid, text) SELECT id, text FROM verses WHERE version NOT IN ({q})", cjk)
	db.execute(f"INSERT INTO verses_tri(rowid, text) SELECT id, text FROM verses WHERE version IN ({q})", cjk)
	db.commit()

	print("copying study data…")
	for (name, sql) in sdb.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
		db.execute(sql)
		cols = len(sdb.execute(f'SELECT * FROM "{name}" LIMIT 0').description)
		db.executemany(f'INSERT INTO "{name}" VALUES ({",".join("?" * cols)})', sdb.execute(f'SELECT * FROM "{name}"'))
	db.executescript("""
		CREATE INDEX xref_from ON cross_references(from_book, from_chapter, from_verse);
		CREATE INDEX tsk_ref ON tsk_entries(book_id, chapter, verse);
		CREATE INDEX mh_ref ON mh_commentary(book, chapter, fromverse);
		CREATE INDEX nave_sub ON nave_subTopics(topic_id);
		CREATE INDEX torrey_sub ON torrey_subtopics(topic_id);
		CREATE INDEX devo_day ON devotional_entries(month, day);
		CREATE VIRTUAL TABLE topics_fts USING fts5(title, source UNINDEXED, topic_id UNINDEXED);
		INSERT INTO topics_fts SELECT title, 'nave', id FROM nave_topics;
		INSERT INTO topics_fts SELECT title, 'torrey', id FROM torrey_topics;
	""")
	index_study(db)
	db.executemany("INSERT INTO meta VALUES (?,?)", [("built_at", time.strftime("%Y-%m-%d %H:%M:%S")), ("schema", "1")])
	db.commit()
	db.execute("ANALYZE")
	db.commit()
	db.execute("VACUUM")
	db.close()
	tmp.replace(out)
	print(f"done: {out} ({out.stat().st_size / 1e6:.0f} MB) in {time.time() - t0:.0f}s")


if __name__ == "__main__":
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument("--modules", type=Path, required=True)
	ap.add_argument("--study", default=STUDY_URL, help="bible_tamil.db, its .zip, or a URL (default: media.truthofbible.org)")
	ap.add_argument("--out", type=Path, required=True)
	ap.add_argument("--download", action="store_true", help="fetch missing web versions from the live catalogue")
	a = ap.parse_args()
	build(a.modules, a.study, a.out, a.download)
