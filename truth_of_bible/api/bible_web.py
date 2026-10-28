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
def search(q: str, version: str = "KJV", scope: str = "all", page=1):
	return _call(Q.search, q, version, scope, _int(page, "page"))


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
