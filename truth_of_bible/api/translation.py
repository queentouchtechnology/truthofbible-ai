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
from frappe.utils import add_days, getdate, nowdate

from truth_of_bible.ai import service
from truth_of_bible.ai.core.exceptions import AiProviderException
from truth_of_bible.ai.core.request import AiMessage, AiRequest
from truth_of_bible.ai.prompts import language_instruction, resolve_prompt
from truth_of_bible.communication.auth import require_admin
from truth_of_bible.rewards import gate

_TASK = "translate_content"
_PUBLISHED = "Published"


def _as_list(value):
	if isinstance(value, str):
		return json.loads(value)
	return value or []


def requires_approval() -> bool:
	"""TOB AI Settings.translation_requires_approval — off by default (see
	that field's own docstring). Read fresh on every call rather than
	cached: an admin flipping this in the Translation screen should take
	effect immediately, not after a worker restart."""
	return bool(frappe.db.get_single_value("TOB AI Settings", "translation_requires_approval"))


def feature_enabled() -> bool:
	"""TOB AI Settings.translation_feature_enabled — the master switch the
	Translation admin screen exposes to hide/show the Translate button
	across every content screen at once. Read fresh, same reasoning as
	requires_approval() above."""
	value = frappe.db.get_single_value("TOB AI Settings", "translation_feature_enabled")
	return True if value is None else bool(value)


@frappe.whitelist(methods=["GET"])
def get_translation_settings():
	return {"requires_approval": requires_approval(), "feature_enabled": feature_enabled()}


@frappe.whitelist(methods=["POST"])
def set_translation_requires_approval(value):
	require_admin()
	enabled = str(value).lower() in ("1", "true", "yes")
	frappe.db.set_single_value("TOB AI Settings", "translation_requires_approval", 1 if enabled else 0)
	return {"requires_approval": enabled}


@frappe.whitelist(methods=["POST"])
def set_translation_feature_enabled(value):
	require_admin()
	enabled = str(value).lower() in ("1", "true", "yes")
	frappe.db.set_single_value("TOB AI Settings", "translation_feature_enabled", 1 if enabled else 0)
	return {"feature_enabled": enabled}


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
	"""Student-facing — keyed by source_name then field. Which statuses
	count as servable depends on TOB AI Settings.translation_requires_
	approval (requires_approval() above): off (default) serves anything
	except an admin's explicit Needs Revision flag, matching how this
	app's other AI content (verse explanations, devotionals) is already
	shown directly with an AI disclaimer rather than gated; on, only
	Published rows are servable and the admin review queue becomes a real
	requirement again. Missing/never-generated fields are silently omitted
	either way, so the client always has a clean fall-back-to-original
	path."""
	if not language or language == "en":
		return {}
	source_names = _as_list(source_names)
	fields = _as_list(fields)
	if not source_names or not fields:
		return {}
	status_condition = ["=", _PUBLISHED] if requires_approval() else ["!=", "Needs Revision"]
	rows = frappe.get_all(
		"TOB Content Translation",
		filters={
			"source_doctype": source_doctype,
			"source_name": ["in", source_names],
			"field": ["in", fields],
			"language": language,
			"translation_status": status_condition,
		},
		fields=["source_name", "field", "translated_text"],
	)
	out: dict = {}
	for r in rows:
		out.setdefault(r.source_name, {})[r.field] = r.translated_text
	return out


def _log_translation_usage(user, source_doctype, source_name, fields, language, *, was_cache_hit, status, error_message=None):
	"""One row per translate_now/translate_local_text call (not per field —
	see rewards.gate.charge_translation's docstring: charging is per-call,
	so usage logging stays at the same granularity, otherwise a multi-field
	call would burn through several days' free quota at once while only
	ever being charged for one)."""
	frappe.get_doc(
		{
			"doctype": "TOB Translation Usage Log",
			"user": user,
			"source_doctype": source_doctype,
			"source_name": source_name,
			"field": ",".join(fields) if isinstance(fields, list) else fields,
			"language": language,
			"was_cache_hit": 1 if was_cache_hit else 0,
			"status": status,
			"error_message": error_message,
		}
	).insert(ignore_permissions=True)


@frappe.whitelist(methods=["GET"])
def translate_now(source_doctype, source_name, fields, language):
	"""On-demand, student-triggered translation — the "Translate" button
	on a content screen calls this directly. Always generates/caches
	(so it exists for the review queue either way), but only returns the
	text immediately when translation_requires_approval is off — when
	it's on, the result is queued for admin review instead and the
	response carries `"_pending": true` with no field text, so the client
	can tell "will show once approved" apart from "translation failed".

	Charging (rewards.gate.charge_translation) only kicks in once at least
	one field here is a genuine cache miss — a call that's entirely cache
	hits (the common case once content has been translated once) never
	touches the gate at all, costs nothing, and carries no "usage" block."""
	if not language or language == "en":
		return {}
	fields = _as_list(fields)
	if not fields:
		return {}
	gated = requires_approval()
	user = frappe.session.user
	out: dict = {}
	generated_any = False
	pending_fields = []
	hit_fields = []
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
		already_servable = existing and existing.source_hash == source_hash and (
			existing.translation_status == _PUBLISHED if gated else existing.translation_status != "Needs Revision"
		)
		if already_servable:
			out[field] = existing.translated_text
			hit_fields.append(field)
			continue
		if existing and existing.source_hash == source_hash and gated:
			# Cached but still awaiting approval — nothing new to generate.
			generated_any = True
			continue
		pending_fields.append((field, source_text))

	if hit_fields:
		_log_translation_usage(
			user, source_doctype, source_name, hit_fields, language, was_cache_hit=True, status="success"
		)

	if pending_fields:
		# Raises (out of free translations, can't afford the next one)
		# before any AI call is made — nothing here is charged for work
		# that didn't happen.
		result = gate.charge_translation(user)
		charged_any = False
		field_names = [f for f, _ in pending_fields]
		error = None
		for field, source_text in pending_fields:
			try:
				doc = _upsert_translation(source_doctype, source_name, field, language, source_text)
				generated_any = True
				charged_any = True
				if not gated:
					out[field] = doc.translated_text
			except AiProviderException as exc:
				error = str(exc)
				continue  # this field just falls back to the original text client-side
		_log_translation_usage(
			user, source_doctype, source_name, field_names, language,
			was_cache_hit=False, status="success" if charged_any else "error", error_message=error,
		)
		if charged_any:
			gate.record_translation_charge(user, result, frappe.generate_hash(length=10))

		if gated and generated_any and not out:
			out["_pending"] = True
		# Only present when translation charging is actually enabled —
		# charge_translation() returns the None-sentinel result above
		# otherwise, same convention bible.qa's usage block follows.
		if result.free_remaining_today is not None:
			out["usage"] = result._asdict()
	elif gated and generated_any and not out:
		out["_pending"] = True
	return out


@frappe.whitelist(methods=["POST"])
def translate_local_text(source_doctype, source_name, text, language):
	"""On-demand translation for content this app doesn't hold as a Frappe
	document at all — Bible Dictionary entries and Matthew Henry
	Commentary both come from the on-device SQLite bundle, and a
	Devotional's text is AI-generated client-side, so none of them has a
	`(doctype, name)` frappe.db.get_value can look up like translate_now's
	other content types do. The source text travels in the request body
	instead (POST, not GET, since commentary text can be long); everything
	else — caching in TOB Content Translation, the source_hash staleness
	check, and the requires_approval() gate — is identical to translate_now,
	just against one field always named "text". Charging (rewards.gate.
	charge_translation) only applies on a genuine cache miss, same as
	translate_now."""
	if not language or language == "en":
		return {}
	if not text:
		return {}
	field = "text"
	gated = requires_approval()
	user = frappe.session.user
	source_hash = _hash(text)
	existing = frappe.db.get_value(
		"TOB Content Translation",
		{"source_doctype": source_doctype, "source_name": source_name, "field": field, "language": language},
		["translated_text", "translation_status", "source_hash"],
		as_dict=True,
	)
	already_servable = existing and existing.source_hash == source_hash and (
		existing.translation_status == _PUBLISHED if gated else existing.translation_status != "Needs Revision"
	)
	if already_servable:
		_log_translation_usage(user, source_doctype, source_name, [field], language, was_cache_hit=True, status="success")
		return {"text": existing.translated_text}
	if existing and existing.source_hash == source_hash and gated:
		return {"_pending": True}

	# Raises before any AI call if out of free translations and can't
	# afford the next one.
	result = gate.charge_translation(user)
	try:
		doc = _upsert_translation(source_doctype, source_name, field, language, text)
	except AiProviderException as exc:
		_log_translation_usage(
			user, source_doctype, source_name, [field], language,
			was_cache_hit=False, status="error", error_message=str(exc),
		)
		return {}
	_log_translation_usage(user, source_doctype, source_name, [field], language, was_cache_hit=False, status="success")
	gate.record_translation_charge(user, result, frappe.generate_hash(length=10))

	usage = {"usage": result._asdict()} if result.free_remaining_today is not None else {}
	if gated:
		return {"_pending": True, **usage}
	return {"text": doc.translated_text, **usage}


# --- Admin: usage & billing visibility --------------------------------------


@frappe.whitelist(methods=["GET"])
def get_translation_usage(from_date: str | None = None, to_date: str | None = None):
	"""Admin usage summary from TOB Translation Usage Log for
	[from_date]..[to_date] (default: the last 30 days) — mirrors
	api/tts.py's get_tts_usage shape. No per-call cost estimate (unlike
	TTS, translation has no simple per-request vendor price to multiply
	by); this is request/hit-rate visibility, same thing get_tts_usage
	gives before its own cost math on top."""
	require_admin()
	end = getdate(to_date) if to_date else getdate(nowdate())
	start = getdate(from_date) if from_date else add_days(end, -29)
	end_exclusive = add_days(end, 1)
	args = {"start": start, "end": end_exclusive}
	where = "creation >= %(start)s AND creation < %(end)s"

	def grouped(column: str) -> list[dict]:
		rows = frappe.db.sql(
			f"""
			SELECT COALESCE({column}, '') AS label,
				COUNT(*) AS requests,
				SUM(was_cache_hit) AS cache_hits,
				SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors
			FROM `tabTOB Translation Usage Log`
			WHERE {where}
			GROUP BY {column}
			ORDER BY requests DESC
			""",
			args,
			as_dict=True,
		)
		return [
			{
				"label": r.label or "Unknown",
				"requests": int(r.requests or 0),
				"cache_hits": int(r.cache_hits or 0),
				"new_translations": int(r.requests or 0) - int(r.cache_hits or 0),
				"errors": int(r.errors or 0),
			}
			for r in rows
		]

	daily = frappe.db.sql(
		f"""
		SELECT DATE(creation) AS day, COUNT(*) AS requests,
			SUM(was_cache_hit) AS cache_hits
		FROM `tabTOB Translation Usage Log`
		WHERE {where}
		GROUP BY DATE(creation)
		ORDER BY day
		""",
		args,
		as_dict=True,
	)

	recent = frappe.get_all(
		"TOB Translation Usage Log",
		filters=[["creation", ">=", start], ["creation", "<", end_exclusive]],
		fields=["creation", "user", "source_doctype", "field", "language", "was_cache_hit", "status", "error_message"],
		order_by="creation desc",
		limit_page_length=25,
	)

	by_language = grouped("language")
	by_doctype = grouped("source_doctype")
	return {
		"from_date": str(start),
		"to_date": str(end),
		"totals": {
			"requests": sum(r["requests"] for r in by_language),
			"cache_hits": sum(r["cache_hits"] for r in by_language),
			"new_translations": sum(r["new_translations"] for r in by_language),
			"errors": sum(r["errors"] for r in by_language),
		},
		"by_language": by_language,
		"by_source_doctype": by_doctype,
		"daily": [
			{"date": str(d.day), "requests": int(d.requests or 0), "cache_hits": int(d.cache_hits or 0)}
			for d in daily
		],
		"recent": [
			{
				"created_at": str(r.creation),
				"user": r.user,
				"source_doctype": r.source_doctype,
				"field": r.field,
				"language": r.language,
				"cached": bool(r.was_cache_hit),
				"status": r.status,
				"error_message": r.error_message,
			}
			for r in recent
		],
	}


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
