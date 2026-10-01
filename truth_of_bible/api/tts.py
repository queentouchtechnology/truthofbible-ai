"""Text-to-speech — the Premium (Google Cloud TTS) alternative to the
app's free on-device voice. One student-facing endpoint (`synthesize`)
does cache-check -> call vendor -> cache -> log, so replaying the same
text+locale+voice combination never re-pays Google (see
TOB TTS Audio Cache's own docstring). Admin settings mirror
api/translation.py's get/set shape exactly.

Access control: `synthesize` goes through the exact same
truth_of_bible.ai.service.check_ai_access() every text-generation AI
feature already goes through — one kill switch (TOB AI Settings.ai_enabled)
and one block list (TOB AI Blocked User) cover both, not two parallel
ones — plus its own TOB TTS Provider.enabled switch layered on top, the
same "feature flag under the global gate" layering translation.py's
translation_feature_enabled already uses."""

import hashlib

import frappe
from frappe import _
from frappe.utils import add_days, get_first_day, getdate, now_datetime, nowdate
from frappe.utils.file_manager import save_file

from truth_of_bible.ai.service import check_ai_access
from truth_of_bible.communication.auth import require_admin
from truth_of_bible.tts import pricing as tts_pricing
from truth_of_bible.tts import service as tts_service
from truth_of_bible.tts.usage import record_tts_usage

_PROVIDER_KEY = "google"


def _hash(text: str, locale: str, voice_type: str | None, audio_encoding: str) -> str:
	key = f"{text}|{locale}|{voice_type or ''}|{audio_encoding}"
	return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _language_code(locale: str) -> str | None:
	"""TOB TTS Usage Log.language is a Link to Language, whose rows are
	plain codes ('ta', 'en') — a full BCP-47 locale like 'ta-IN' would
	fail that Link's existence check. Strip the region suffix; falls back
	to None (an empty Link is valid) if the base code isn't a real
	Language row either, rather than letting a bad locale block logging."""
	code = (locale or "").split("-")[0].lower()
	return code if frappe.db.exists("Language", code) else None


@frappe.whitelist(methods=["GET"])
def get_tts_settings():
	settings = tts_service.get_settings()
	if settings is None:
		return {"enabled": False}
	return {
		"enabled": settings.enabled,
		"voice_type": settings.voice_type,
		"price_per_million_chars_usd": settings.price_per_million_chars_usd,
	}


@frappe.whitelist(methods=["POST"])
def set_tts_provider_settings(
	enabled=None,
	voice_type=None,
	audio_encoding=None,
	price_per_million_chars_usd=None,
	character_limit_per_request=None,
	api_key=None,
):
	"""Get-or-creates the single 'google' TOB TTS Provider row — it won't
	exist until an admin first saves this screen. api_key is only
	overwritten when a non-blank value is actually submitted, so a
	re-save from a UI that shows the key masked/blank never wipes the
	stored secret."""
	require_admin()
	if frappe.db.exists("TOB TTS Provider", _PROVIDER_KEY):
		doc = frappe.get_doc("TOB TTS Provider", _PROVIDER_KEY)
	else:
		doc = frappe.get_doc({"doctype": "TOB TTS Provider", "provider_key": _PROVIDER_KEY})

	if enabled is not None:
		doc.enabled = 1 if str(enabled).lower() in ("1", "true", "yes") else 0
	if voice_type:
		doc.voice_type = voice_type
	if audio_encoding:
		doc.audio_encoding = audio_encoding
	if price_per_million_chars_usd is not None:
		doc.price_per_million_chars_usd = float(price_per_million_chars_usd)
	if character_limit_per_request is not None:
		doc.character_limit_per_request = int(character_limit_per_request)
	if api_key:
		doc.api_key = api_key

	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"enabled": bool(doc.enabled)}


@frappe.whitelist(methods=["POST"])
def synthesize(text: str, locale: str, task: str = "general"):
	"""On-demand speech synthesis for the Premium voice option. Returns
	{"audio_url": ..., "cached": bool}. Raises a clean frappe.throw on any
	failure — the client falls back to the free on-device voice rather
	than surfacing this to the user (see tts_playback_controller.dart)."""
	check_ai_access()

	text = (text or "").strip()
	if not text:
		frappe.throw(_("No text to speak."))

	settings = tts_service.get_settings()
	if settings is None or not settings.enabled:
		frappe.throw(_("Premium voice is currently unavailable."))
	if len(text) > settings.character_limit_per_request:
		frappe.throw(_("That text is too long to read aloud ({0} character limit).").format(settings.character_limit_per_request))

	language_code = _language_code(locale)
	cache_key = _hash(text, locale, settings.voice_type, settings.audio_encoding)
	existing = frappe.db.get_value("TOB TTS Audio Cache", {"cache_key": cache_key}, "name")
	if existing:
		cache_doc = frappe.get_doc("TOB TTS Audio Cache", existing)
		cache_doc.hit_count = (cache_doc.hit_count or 0) + 1
		cache_doc.last_used = now_datetime()
		cache_doc.save(ignore_permissions=True)
		frappe.db.commit()
		record_tts_usage(
			task=task, language=language_code, provider=_PROVIDER_KEY, voice_type=settings.voice_type,
			was_cache_hit=True, character_count=len(text), estimated_cost_usd=0, status="success",
		)
		return {"audio_url": cache_doc.audio_file, "cached": True}

	try:
		audio_bytes, voice_name = tts_service.synthesize_speech(text, locale)
	except (tts_service.TtsProviderDisabled, tts_service.TtsProviderError) as exc:
		record_tts_usage(
			task=task, language=language_code, provider=_PROVIDER_KEY, voice_type=settings.voice_type,
			was_cache_hit=False, character_count=len(text), estimated_cost_usd=0, status="error",
			error_message=str(exc),
		)
		frappe.throw(_("Could not generate speech: {0}").format(str(exc)))

	character_count = len(text)
	estimated_cost_usd = (character_count / 1_000_000) * settings.price_per_million_chars_usd

	cache_doc = frappe.get_doc(
		{
			"doctype": "TOB TTS Audio Cache",
			"cache_key": cache_key,
			"locale": locale,
			"voice_type": settings.voice_type,
			"character_count": character_count,
			"source_text": text[:2000],
			"hit_count": 0,
			"last_used": now_datetime(),
		}
	).insert(ignore_permissions=True)

	extension = "ogg" if settings.audio_encoding == "OGG_OPUS" else ("wav" if settings.audio_encoding == "LINEAR16" else "mp3")
	file_doc = save_file(
		fname=f"{cache_doc.name}.{extension}",
		content=audio_bytes,
		dt="TOB TTS Audio Cache",
		dn=cache_doc.name,
		is_private=0,
	)
	cache_doc.audio_file = file_doc.file_url
	cache_doc.save(ignore_permissions=True)
	frappe.db.commit()

	record_tts_usage(
		task=task, language=language_code, provider=_PROVIDER_KEY, voice_type=settings.voice_type,
		was_cache_hit=False, character_count=character_count, estimated_cost_usd=estimated_cost_usd, status="success",
	)
	# voice_name included temporarily for on-device diagnosis of a report
	# that Premium and Free sound identical — remove once confirmed.
	return {"audio_url": file_doc.file_url, "cached": False, "voice_name": voice_name}


# --- Admin: voice catalog / comparison -------------------------------------

_VOICE_CACHE_KEY = "tob_tts_voice_catalog"
_VOICE_CACHE_SECONDS = 6 * 60 * 60
_PREVIEW_MAX_CHARS = 300


def _all_voices() -> list[dict]:
	"""Every Google voice, cached for a few hours — the list only changes
	when Google launches voices, and one call returns all languages."""
	cached = frappe.cache().get_value(_VOICE_CACHE_KEY)
	if cached is not None:
		return cached
	voices = tts_service.list_voices()
	frappe.cache().set_value(_VOICE_CACHE_KEY, voices, expires_in_sec=_VOICE_CACHE_SECONDS)
	return voices


def _language_names() -> dict:
	return {r.name: r.language_name for r in frappe.get_all("Language", fields=["name", "language_name"])}


@frappe.whitelist(methods=["GET"])
def get_tts_voice_catalog(language_code: str | None = None, refresh=None):
	"""Admin voice comparison. Returns every language Google has voices
	for (with voice counts and tiers), the voices for [language_code], and
	the list price / monthly free allowance of every tier."""
	require_admin()
	if str(refresh).lower() in ("1", "true", "yes"):
		frappe.cache().delete_value(_VOICE_CACHE_KEY)
	try:
		voices = _all_voices()
	except (tts_service.TtsProviderDisabled, tts_service.TtsProviderError) as exc:
		frappe.throw(_("Could not load voices: {0}").format(str(exc)))

	names = _language_names()
	languages: dict[str, dict] = {}
	for voice in voices:
		tier = tts_pricing.tier_for_voice_name(voice.get("name", ""))
		for code in voice.get("languageCodes") or []:
			row = languages.setdefault(
				code,
				{"code": code, "name": names.get(code.split("-")[0].lower()) or code, "voice_count": 0, "tiers": set()},
			)
			row["voice_count"] += 1
			row["tiers"].add(tier)
	language_list = sorted(
		({**row, "tiers": sorted(row["tiers"])} for row in languages.values()),
		key=lambda r: (r["name"].lower(), r["code"]),
	)

	selected = []
	if language_code:
		prefix = language_code + "-"
		for voice in voices:
			if language_code not in (voice.get("languageCodes") or []):
				continue
			name = voice.get("name", "")
			selected.append(
				{
					"name": name,
					# 'ta-IN-Chirp3-HD-Achernar' -> 'Chirp3-HD-Achernar'
					"short_name": name[len(prefix) :] if name.startswith(prefix) else name,
					"tier": tts_pricing.tier_for_voice_name(name),
					"gender": (voice.get("ssmlGender") or "").title(),
					"sample_rate_hz": voice.get("naturalSampleRateHertz"),
				}
			)
		selected.sort(key=lambda v: v["name"])

	settings = tts_service.get_settings()
	return {
		"languages": language_list,
		"language_code": language_code,
		"voices": selected,
		"tiers": tts_pricing.TIERS,
		"current_voice_type": settings.voice_type if settings else None,
	}


@frappe.whitelist(methods=["POST"])
def preview_tts_voice(voice_name: str, language_code: str, text: str):
	"""Admin voice comparison: speaks [text] in exactly [voice_name]. Works
	while Premium is switched off. Cached like `synthesize`, and logged
	(task 'voice_preview') at that voice's tier, so previews show up in
	the usage screen too."""
	require_admin()
	text = (text or "").strip()[:_PREVIEW_MAX_CHARS]
	if not text:
		frappe.throw(_("Enter some text to preview."))
	settings = tts_service.get_settings()
	if settings is None:
		frappe.throw(_("Save the Voice (TTS) Settings screen first."))

	tier = tts_pricing.tier_for_voice_name(voice_name)
	language = _language_code(language_code)
	cache_key = _hash(text, language_code, voice_name, settings.audio_encoding)
	existing = frappe.db.get_value(
		"TOB TTS Audio Cache", {"cache_key": cache_key}, ["name", "audio_file"], as_dict=True
	)
	if existing and existing.audio_file:
		record_tts_usage(
			task="voice_preview", language=language, provider=_PROVIDER_KEY, voice_type=tier,
			was_cache_hit=True, character_count=len(text), estimated_cost_usd=0, status="success",
		)
		return {"audio_url": existing.audio_file, "cached": True}

	try:
		audio_bytes, _ = tts_service.synthesize_speech(
			text, language_code, voice_name=voice_name, require_enabled=False
		)
	except (tts_service.TtsProviderDisabled, tts_service.TtsProviderError) as exc:
		record_tts_usage(
			task="voice_preview", language=language, provider=_PROVIDER_KEY, voice_type=tier,
			was_cache_hit=False, character_count=len(text), estimated_cost_usd=0, status="error",
			error_message=str(exc),
		)
		frappe.throw(_("Could not generate speech: {0}").format(str(exc)))

	cache_doc = frappe.get_doc(
		{
			"doctype": "TOB TTS Audio Cache",
			"cache_key": cache_key,
			"locale": language_code,
			"voice_type": voice_name,
			"character_count": len(text),
			"source_text": text,
			"hit_count": 0,
			"last_used": now_datetime(),
		}
	).insert(ignore_permissions=True)
	extension = "ogg" if settings.audio_encoding == "OGG_OPUS" else ("wav" if settings.audio_encoding == "LINEAR16" else "mp3")
	file_doc = save_file(
		fname=f"{cache_doc.name}.{extension}",
		content=audio_bytes,
		dt="TOB TTS Audio Cache",
		dn=cache_doc.name,
		is_private=0,
	)
	cache_doc.audio_file = file_doc.file_url
	cache_doc.save(ignore_permissions=True)
	frappe.db.commit()
	record_tts_usage(
		task="voice_preview", language=language, provider=_PROVIDER_KEY, voice_type=tier,
		was_cache_hit=False, character_count=len(text),
		estimated_cost_usd=len(text) / 1_000_000 * tts_pricing.price_per_million(tier), status="success",
	)
	return {"audio_url": file_doc.file_url, "cached": False}


# --- Admin: usage & estimated billing ----------------------------------------

_BILLABLE_SQL = "CASE WHEN status = 'success' AND was_cache_hit = 0 THEN character_count ELSE 0 END"


@frappe.whitelist(methods=["GET"])
def get_tts_usage(from_date: str | None = None, to_date: str | None = None):
	"""Admin usage/billing summary from TOB TTS Usage Log for
	[from_date]..[to_date] (default: the last 30 days), plus this calendar
	month's free-allowance use and estimated bill per tier.

	Cost is recomputed from each row's tier at Google's list price
	(tts/pricing.py) rather than read from the logged estimated_cost_usd,
	which used the hand-entered TOB TTS Provider price (often 0). Still an
	estimate: Google's real invoice (taxes, credits, discounts) lives in
	Cloud Billing, which the TTS API key can't read."""
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
				SUM(character_count) AS characters,
				SUM({_BILLABLE_SQL}) AS billable_characters,
				SUM(was_cache_hit) AS cache_hits,
				SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors
			FROM `tabTOB TTS Usage Log`
			WHERE {where}
			GROUP BY {column}
			ORDER BY billable_characters DESC, requests DESC
			""",
			args,
			as_dict=True,
		)
		return [
			{
				"label": r.label or "Unknown",
				"requests": int(r.requests or 0),
				"characters": int(r.characters or 0),
				"billable_characters": int(r.billable_characters or 0),
				"cache_hits": int(r.cache_hits or 0),
				"errors": int(r.errors or 0),
			}
			for r in rows
		]

	by_tier = grouped("voice_type")
	for row in by_tier:
		row["price_per_million_usd"] = tts_pricing.price_per_million(row["label"])
		row["list_cost_usd"] = row["billable_characters"] / 1_000_000 * row["price_per_million_usd"]

	daily = frappe.db.sql(
		f"""
		SELECT DATE(creation) AS day, COUNT(*) AS requests, SUM({_BILLABLE_SQL}) AS billable_characters
		FROM `tabTOB TTS Usage Log`
		WHERE {where}
		GROUP BY DATE(creation)
		ORDER BY day
		""",
		args,
		as_dict=True,
	)

	recent = frappe.get_all(
		"TOB TTS Usage Log",
		filters=[["creation", ">=", start], ["creation", "<", end_exclusive]],
		fields=["creation", "user", "task", "language", "voice_type", "was_cache_hit", "character_count", "status", "error_message"],
		order_by="creation desc",
		limit_page_length=25,
	)

	# This calendar month against Google's monthly free allowance, per tier.
	month_start = get_first_day(nowdate())
	month_rows = frappe.db.sql(
		f"""
		SELECT COALESCE(voice_type, '') AS tier, SUM({_BILLABLE_SQL}) AS billable_characters
		FROM `tabTOB TTS Usage Log`
		WHERE creation >= %(start)s
		GROUP BY voice_type
		""",
		{"start": month_start},
		as_dict=True,
	)
	this_month = []
	for r in month_rows:
		info = tts_pricing.tier_info(r.tier)
		used = int(r.billable_characters or 0)
		free = info["free_chars_per_month"] if info else 0
		price = info["price_per_million_usd"] if info else 0.0
		chargeable = max(0, used - free)
		this_month.append(
			{
				"tier": r.tier or "Unknown",
				"billable_characters": used,
				"free_chars_per_month": free,
				"chargeable_characters": chargeable,
				"price_per_million_usd": price,
				"estimated_bill_usd": chargeable / 1_000_000 * price,
			}
		)

	return {
		"from_date": str(start),
		"to_date": str(end),
		"totals": {
			"requests": sum(r["requests"] for r in by_tier),
			"characters": sum(r["characters"] for r in by_tier),
			"billable_characters": sum(r["billable_characters"] for r in by_tier),
			"cache_hits": sum(r["cache_hits"] for r in by_tier),
			"errors": sum(r["errors"] for r in by_tier),
			"list_cost_usd": sum(r["list_cost_usd"] for r in by_tier),
		},
		"by_tier": by_tier,
		"by_language": grouped("language"),
		"by_task": grouped("task"),
		"daily": [
			{"date": str(d.day), "requests": int(d.requests or 0), "billable_characters": int(d.billable_characters or 0)}
			for d in daily
		],
		"this_month": {
			"month_start": str(month_start),
			"tiers": this_month,
			"estimated_bill_usd": sum(t["estimated_bill_usd"] for t in this_month),
		},
		"recent": [
			{
				"created_at": str(r.creation),
				"user": r.user,
				"task": r.task,
				"language": r.language,
				"voice_type": r.voice_type,
				"cached": bool(r.was_cache_hit),
				"characters": int(r.character_count or 0),
				"status": r.status,
				"error_message": r.error_message,
			}
			for r in recent
		],
	}
