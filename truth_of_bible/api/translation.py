"""Generic content translation — routes through the same `ai/service.py`
pipeline every other AI feature uses (task="translate_content"), caching
results in `TOB Content Translation` so the same field is never
re-translated for the same source text. See that doctype's own docstring
for why `source_doctype`/`source_name`/`field` are plain strings rather
than a Link: this has to translate content this app doesn't own (Frappe
LMS's own doctypes, for a future Quiz Questions content type) without
ever writing back to them — every write here targets only
TOB Content Translation.

Bulk jobs run via `frappe.enqueue` — a single admin request can ask for
hundreds of individual AI calls (e.g. 52 memory verses x 2 fields x 3
languages), which would time out as a synchronous HTTP request. Progress
is never tracked in a separate doctype — `get_translation_status` simply
counts how many of the expected TOB Content Translation rows already
exist, recomputed on each poll.
"""

import hashlib
import json

import frappe
from frappe import _

from truth_of_bible.ai import service
from truth_of_bible.ai.core.exceptions import AiProviderException
from truth_of_bible.ai.core.request import AiMessage, AiRequest
from truth_of_bible.ai.prompts import language_instruction, resolve_prompt
from truth_of_bible.communication.auth import require_admin

_TASK = "translate_content"
_PUBLISHED = "Published"


def _as_list(value):
	if isinstance(value, str):
		return json.loads(value)
	return value or []


def _hash(text: str) -> str:
	return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _translate_text(text: str, language: str):
	"""Returns (translated_text, provider, model). Raises AiProviderException on failure."""
	system_prompt = resolve_prompt(_TASK, language) + language_instruction(language)
	request = AiRequest(
		task=_TASK,
		language=language,
		messages=[
			AiMessage(role="system", content=system_prompt),
			AiMessage(role="user", content=text),
		],
	)
	response = service.generate(request)
	return response.content, response.provider, response.model


def _upsert_translation(source_doctype, source_name, field, language, source_text):
	source_hash = _hash(source_text)
	translated_text, provider, model = _translate_text(source_text, language)
	existing_name = frappe.db.get_value(
		"TOB Content Translation",
		{"source_doctype": source_doctype, "source_name": source_name, "field": field, "language": language},
		"name",
	)
	if existing_name:
		doc = frappe.get_doc("TOB Content Translation", existing_name)
		doc.translated_text = translated_text
		doc.source_hash = source_hash
		# Re-translating (e.g. after a source edit) drops it back to
		# Machine Translated even if it was previously Published — a
		# changed source means the old Published text may no longer match
		# it, so it must go through review again rather than silently
		# staying "approved" for text that's since changed underneath it.
		doc.translation_status = "Machine Translated"
		doc.provider = provider
		doc.model = model
		doc.translated_by = "AI"
		doc.reviewed_by = None
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "TOB Content Translation",
				"source_doctype": source_doctype,
				"source_name": source_name,
				"field": field,
				"language": language,
				"translated_text": translated_text,
				"source_hash": source_hash,
				"translation_status": "Machine Translated",
				"provider": provider,
				"model": model,
				"translated_by": "AI",
			}
		).insert(ignore_permissions=True)
	frappe.db.commit()
	return doc


@frappe.whitelist(methods=["POST"])
def translate_field(source_doctype, source_name, field, target_language):
	"""Single-field translate — the admin bulk-translate screen's "retry
	this one" action, and what bulk_translate's background job calls in a
	loop."""
	require_admin()
	source_text = frappe.db.get_value(source_doctype, source_name, field)
	if not source_text:
		frappe.throw(_("{0}.{1} has no {2} to translate.").format(source_doctype, source_name, field))
	try:
		doc = _upsert_translation(source_doctype, source_name, field, target_language, source_text)
	except AiProviderException as exc:
		frappe.throw(_("Could not translate: {0}").format(str(exc)), frappe.ValidationError)
	return {"name": doc.name, "translated_text": doc.translated_text, "translation_status": doc.translation_status}


def _bulk_translate_job(source_doctype, docs, fields, target_languages):
	"""Runs in a background worker (see bulk_translate's frappe.enqueue
	call) — never lets one row/field/language's failure stop the rest;
	each failure is logged and simply counted as not-yet-translated by
	get_translation_status's own recount on the next poll."""
	for doc_name in docs:
		for field in fields:
			source_text = frappe.db.get_value(source_doctype, doc_name, field)
			if not source_text:
				continue
			for language in target_languages:
				try:
					_upsert_translation(source_doctype, doc_name, field, language, source_text)
				except Exception:
					frappe.log_error(title="Bulk translation row failed", message=frappe.get_traceback())


@frappe.whitelist(methods=["POST"])
def bulk_translate(source_doctype, filters, fields, target_languages):
	"""Queues a background job translating every field of every matching
	document into every target language. filters/fields/target_languages
	arrive JSON-encoded (a POST body's nested list/dict values come back
	as JSON strings, same as mark_attendance's own entries param)."""
	require_admin()
	filters = json.loads(filters) if isinstance(filters, str) else (filters or {})
	fields = _as_list(fields)
	target_languages = _as_list(target_languages)
	if not fields:
		frappe.throw(_("Pick at least one field to translate."))
	if not target_languages:
		frappe.throw(_("Pick at least one target language."))

	docs = frappe.get_all(source_doctype, filters=filters, pluck="name")
	if not docs:
		frappe.throw(_("No matching documents found."))

	frappe.enqueue(
		"truth_of_bible.api.translation._bulk_translate_job",
		queue="long",
		timeout=3600,
		source_doctype=source_doctype,
		docs=docs,
		fields=fields,
		target_languages=target_languages,
	)
	return {"queued_documents": len(docs), "fields": fields, "target_languages": target_languages}


@frappe.whitelist(methods=["GET"])
def get_translation_status(source_doctype, source_names, fields, target_languages):
	"""Recomputed from TOB Content Translation on every call — the admin
	bulk-translate screen polls this while a background job is running."""
	require_admin()
	source_names = _as_list(source_names)
	fields = _as_list(fields)
	target_languages = _as_list(target_languages)
	if not source_names or not fields or not target_languages:
		return {"expected_per_language": 0, "by_language": {}}

	rows = frappe.get_all(
		"TOB Content Translation",
		filters={
			"source_doctype": source_doctype,
			"source_name": ["in", source_names],
			"field": ["in", fields],
			"language": ["in", target_languages],
		},
		fields=["language", "translation_status"],
	)
	expected_per_language = len(source_names) * len(fields)
	by_language = {}
	for lang in target_languages:
		lang_rows = [r for r in rows if r.language == lang]
		by_language[lang] = {
			"translated": len(lang_rows),
			"published": len([r for r in lang_rows if r.translation_status == _PUBLISHED]),
			"needs_review": len([r for r in lang_rows if r.translation_status != _PUBLISHED]),
		}
	return {"expected_per_language": expected_per_language, "by_language": by_language}


@frappe.whitelist(methods=["GET"])
def list_pending_translations(source_doctype=None, target_language=None):
	"""The review queue — every row not yet Published, for the admin
	approve/reject screen."""
	require_admin()
	filters = {"translation_status": ["!=", _PUBLISHED]}
	if source_doctype:
		filters["source_doctype"] = source_doctype
	if target_language:
		filters["language"] = target_language
	return frappe.get_all(
		"TOB Content Translation",
		filters=filters,
		fields=["name", "source_doctype", "source_name", "field", "language", "translated_text", "translation_status", "modified"],
		order_by="modified desc",
		limit_page_length=200,
	)


@frappe.whitelist(methods=["POST"])
def publish_translation(name):
	require_admin()
	frappe.db.set_value(
		"TOB Content Translation", name,
		{"translation_status": _PUBLISHED, "reviewed_by": frappe.session.user},
	)
	frappe.db.commit()
	return {"status": _PUBLISHED}


@frappe.whitelist(methods=["POST"])
def reject_translation(name):
	require_admin()
	frappe.db.set_value(
		"TOB Content Translation", name,
		{"translation_status": "Needs Revision", "reviewed_by": frappe.session.user},
	)
	frappe.db.commit()
	return {"status": "Needs Revision"}


@frappe.whitelist(methods=["GET"])
def get_translated_fields(source_doctype, source_names, fields, language):
	"""Student-facing — returns every translation except one an admin has
	explicitly flagged Needs Revision, keyed by source_name then field.
	Not gated on Published: this app's own existing AI content (verse
	explanations, devotionals) is already shown directly with an
	AI-generated disclaimer rather than held behind admin approval, and
	translation now follows the same policy — the admin review queue
	(list_pending_translations/publish_translation/reject_translation) is
	optional curation, not a requirement for a translation to be servable.
	Missing/never-generated fields are silently omitted either way, so the
	client always has a clean fall-back-to-original path."""
	if not language or language == "en":
		return {}
	source_names = _as_list(source_names)
	fields = _as_list(fields)
	if not source_names or not fields:
		return {}
	rows = frappe.get_all(
		"TOB Content Translation",
		filters={
			"source_doctype": source_doctype,
			"source_name": ["in", source_names],
			"field": ["in", fields],
			"language": language,
			"translation_status": ["!=", "Needs Revision"],
		},
		fields=["source_name", "field", "translated_text"],
	)
	out: dict = {}
	for r in rows:
		out.setdefault(r.source_name, {})[r.field] = r.translated_text
	return out


@frappe.whitelist(methods=["GET"])
def translate_now(source_doctype, source_name, fields, language):
	"""On-demand, student-triggered translation — the "Translate" button
	on a content screen calls this directly (no admin involved) rather
	than waiting for a bulk job or approval. Generates synchronously since
	this is always a small number of fields for one document, unlike
	bulk_translate's hundreds of calls. Reuses the same cache-then-
	generate path as everything else here, so a verse translated this way
	is exactly as reusable (and as subject to an admin later flagging it
	Needs Revision) as one produced by a bulk job."""
	if not language or language == "en":
		return {}
	fields = _as_list(fields)
	if not fields:
		return {}
	out: dict = {}
	for field in fields:
		source_text = frappe.db.get_value(source_doctype, source_name, field)
		if not source_text:
			continue
		source_hash = _hash(source_text)
		existing = frappe.db.get_value(
			"TOB Content Translation",
			{"source_doctype": source_doctype, "source_name": source_name, "field": field, "language": language},
			["translated_text", "translation_status", "source_hash"],
			as_dict=True,
		)
		if existing and existing.translation_status != "Needs Revision" and existing.source_hash == source_hash:
			out[field] = existing.translated_text
			continue
		try:
			doc = _upsert_translation(source_doctype, source_name, field, language, source_text)
			out[field] = doc.translated_text
		except AiProviderException:
			continue  # this field just falls back to the original text client-side
	return out


@frappe.whitelist(methods=["GET"])
def get_supported_languages():
	"""The curated content-translation language set — deliberately not the
	AI feature's own ~80-language list (see Language.content_translation_
	enabled's own docstring)."""
	return frappe.get_all(
		"Language",
		filters={"enabled": 1, "content_translation_enabled": 1},
		fields=["name as code", "language_name", "native_name", "direction", "is_default"],
		order_by="is_default desc, native_name asc",
	)
