"""Public, read-only Bible API for truthofbible.org's web Bible (reading, search, compare, cross
references, TSK, commentary, Strong's, topics, devotionals). Thin wrappers over
truth_of_bible.bible_web.queries; the data is the SQLite file built by bible_web/build.py, located by
TOB Website Settings → Bible Database Path. Everything here is guest-accessible and GET-only, so
nginx can cache the responses."""

import os
import threading

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from truth_of_bible.bible_web import queries as Q

_lock = threading.Lock()
_con = None
_con_key = None


def _db():
	"""One read-only connection per worker, reopened when the file is rebuilt (new mtime)."""
	global _con, _con_key
	path = frappe.db.get_single_value("TOB Website Settings", "bible_db_path") or "private/bible/tob_bible_web.db"
	if not os.path.isabs(path):
		path = frappe.get_site_path(path)
	try:
		key = (path, os.path.getmtime(path))
	except OSError:
		frappe.throw(_("The web Bible is not available yet."), frappe.DoesNotExistError)
	with _lock:
		if _con_key != key:
			_con = Q.connect(path)
			_con_key = key
	return _con


def _call(fn, *args, **kwargs):
	try:
		result = fn(_db(), *args, **kwargs)
	except LookupError as e:
		frappe.throw(str(e), frappe.DoesNotExistError)
	if result is None:
		frappe.throw(_("Not found"), frappe.DoesNotExistError)
	return result


def _int(value, name):
	try:
		return int(value)
	except (TypeError, ValueError):
		frappe.throw(_("{0} must be a number").format(name))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def versions():
	return _call(Q.versions)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def books(version: str = "KJV"):
	return _call(Q.books, version)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def chapter(version: str, book, chapter, strongs=0):
	return _call(Q.chapter, version, _int(book, "book"), _int(chapter, "chapter"), bool(_int(strongs or 0, "strongs")))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def passage(version: str, book, chapter, start, end=None):
	return _call(Q.passage, version, _int(book, "book"), _int(chapter, "chapter"), _int(start, "start"), _int(end, "end") if end else None)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def compare(versions: str, book, chapter):
	codes = [c.strip() for c in (versions or "").split(",") if c.strip()]
	if not codes:
		frappe.throw(_("Choose at least one version."))
	return _call(Q.compare, codes, _int(book, "book"), _int(chapter, "chapter"))


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=120, seconds=60)
def search(q: str, version: str = "KJV", scope: str = "all", page=1, sort: str = "relevance"):
	"""sort: relevance (exact phrase first, then best match) or bible (canonical order)."""
	return _call(Q.search, q, version, scope, _int(page, "page"), "bible" if sort == "bible" else "relevance")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def cross_references(book, chapter, verse, version: str = "KJV"):
	return _call(Q.cross_references, _int(book, "book"), _int(chapter, "chapter"), _int(verse, "verse"), version)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def tsk(book, chapter, verse):
	return _call(Q.tsk, _int(book, "book"), _int(chapter, "chapter"), _int(verse, "verse"))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def commentary(book, chapter):
	return _call(Q.commentary, _int(book, "book"), _int(chapter, "chapter"))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def strongs(code: str):
	return _call(Q.strongs, code)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def dictionary(word: str):
	return _call(Q.dictionary, word)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def topics(q: str):
	return _call(Q.topics, q)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def topic(source: str, id):
	if source not in ("nave", "torrey"):
		frappe.throw(_("Unknown topic source"))
	return _call(Q.topic, source, _int(id, "id"))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def devotional(month, day):
	return _call(Q.devotional, _int(month, "month"), _int(day, "day"))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def parse_refs(text: str):
	return _call(Q.parse_refs, text)


def _entities():
	"""Published characters, places, events and themes (the app's own lists), as rankable docs.
	Cached for 10 minutes; editors' changes show up after that."""
	from truth_of_bible.api import bible_characters, bible_events, bible_places, bible_themes
	from truth_of_bible.bible_web.rank import Doc

	def load():
		return {
			"Characters": [
				{"title": c["title"], "subtitle": c["role"], "keywords": [c["testament"] or ""], "data": {"id": c["character"], "passages": c["relevant_passages"]}}
				for c in bible_characters.list_characters()["characters"]
			],
			"Places": [
				{"title": p["title"], "subtitle": p["region"] or p["category"] or "", "keywords": [p["description"][:200]],
				 "data": {"id": p["place"], "passages": p["relevant_passages"] or ([p["primary_verse_ref"]] if p["primary_verse_ref"] else []), "description": p["description"], "photo": p["photo_url"], "facts": p["facts"]}}
				for p in bible_places.list_places()["places"]
			],
			"Events": [
				{"title": e["title"], "subtitle": e.get("era") or "", "keywords": [e.get("description", "")[:200]], "data": {"id": e.get("event"), "passages": e.get("relevant_passages", []), "description": e.get("description", "")}}
				for e in bible_events.list_events()["events"]
			],
			"Themes": [
				{"title": t["title"], "subtitle": (t.get("description") or "")[:120], "keywords": [], "data": {"id": t.get("theme"), "passages": t.get("relevant_passages", []), "description": t.get("description", "")}}
				for t in bible_themes.list_themes()["themes"]
			],
		}

	cache = frappe.cache()
	raw = cache.get_value("tob_web_bible_entities")
	if raw is None:
		raw = load()
		cache.set_value("tob_web_bible_entities", raw, expires_in_sec=600)
	return {typ: [Doc(typ, x["title"], x["subtitle"], x["keywords"], x["data"]) for x in items] for typ, items in raw.items()}


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=120, seconds=60)
def unified(q: str, version: str = "KJV"):
	"""One search across everything, like the app's search bar: reference, ranked entities, Strong's,
	commentary, devotionals and verses."""
	try:
		entities = _entities()
	except Exception:
		frappe.log_error(title="Web Bible: entity lists for search failed", message=frappe.get_traceback())
		entities = {}
	return _call(Q.unified, q, version, entities)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def verse_counts(version: str, book):
	return _call(Q.verse_counts, version, _int(book, "book"))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def verse_all(book, chapter, verse):
	return _call(Q.verse_all, _int(book, "book"), _int(chapter, "chapter"), _int(verse, "verse"))
