"""Optional wallet charge for AI Q&A, Translation and Premium Voice (TTS)
after a daily free allowance — every one of the three is OFF by default, so
all three stay free until an admin turns them on. Settings live on the
`TOB AI Settings` Single doctype (ai_charge_enabled/ai_free_per_day/
ai_cost, translation_*, tts_*) rather than site_config.json, so they are
admin-panel-editable (get_charging_settings/set_charging_settings below),
the same way TOB AI Settings' translation_requires_approval/
translation_feature_enabled already are. A member out of free uses with
too little wallet balance gets a clear message instead of the
answer/translation/audio; the wallet is debited only after the underlying
call actually succeeded.

AI Q&A (qa/qa_followup) is a flat per-call charge — `charge_ai` wraps the
whole endpoint, since every call is a fresh AI generation with nothing to
cache. Translation and TTS both cache their results server-side (a second
student asking for the same translation/audio costs nothing), so they
cannot use the same wrap-the-whole-endpoint shape: charging there has to
happen only at the exact point a cache *miss* is confirmed, which only the
caller (api/translation.py, api/tts.py) knows — see charge_translation/
charge_tts below, called inline rather than as decorators.
"""

import functools
from typing import NamedTuple

import frappe
from frappe import _
from frappe.utils import nowdate

from truth_of_bible.communication.auth import require_admin
from truth_of_bible.rewards import engine

_CHARGING_FIELDS = (
	"ai_charge_enabled",
	"ai_free_per_day",
	"ai_cost",
	"translation_charge_enabled",
	"translation_free_per_day",
	"translation_cost",
	"tts_charge_enabled",
	"tts_free_per_day",
	"tts_cost",
)


class ChargeResult(NamedTuple):
	"""What a successful gate check decided — returned so the caller can
	attach a "usage" block to its response (see docs/ai_usage_charging):
	whether this specific call was charged, what it cost, how many free
	uses are left today (after this one), and the wallet balance after any
	debit. `free_remaining_today` is None when charging is off for this
	feature (there's no "remaining" concept to show)."""

	charged: bool
	cost: float
	free_remaining_today: int | None
	wallet_balance: float


def _settings(*fields: str) -> dict:
	"""Fresh read of the given TOB AI Settings fields — no caching, so an
	admin saving the settings screen takes effect on the very next request,
	same immediacy site_config.json had."""
	return {f: frappe.db.get_single_value("TOB AI Settings", f) for f in fields}


@frappe.whitelist(methods=["GET"])
def get_charging_settings():
	require_admin()
	return _settings(*_CHARGING_FIELDS)


@frappe.whitelist(methods=["POST"])
def set_charging_settings(**kwargs):
	require_admin()
	doc = frappe.get_single("TOB AI Settings")
	for field in _CHARGING_FIELDS:
		if field in kwargs and kwargs[field] not in (None, ""):
			value = kwargs[field]
			if field.endswith("_charge_enabled"):
				value = 1 if str(value).lower() in ("1", "true", "yes") else 0
			elif field.endswith("_free_per_day"):
				value = int(value)
			elif field.endswith("_cost"):
				value = float(value)
			doc.set(field, value)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return _settings(*_CHARGING_FIELDS)


@frappe.whitelist(methods=["GET"])
def get_charging_status():
	"""Read-only, any signed-in user (their own status, not an admin
	report) — what the client shows *before* acting (the "3 free today"
	pill on the AI chat input, the Translate button, the Premium voice
	toggle). Always advisory: a status read and the real charge_* gate at
	the point of action aren't atomic, so the actual call is still the
	source of truth (this can't itself block or charge anything)."""
	user = frappe.session.user
	off = {"enabled": False, "free_remaining_today": None, "cost": 0}
	if user in ("Guest", "Administrator"):
		return {"ai": off, "translation": off, "tts": off}

	settings = _settings(*_CHARGING_FIELDS)

	def status(prefix: str, used_today: int) -> dict:
		if not settings[f"{prefix}_charge_enabled"]:
			return off
		free = int(settings[f"{prefix}_free_per_day"] or 0)
		return {
			"enabled": True,
			"free_remaining_today": max(0, free - used_today),
			"cost": float(settings[f"{prefix}_cost"] or 0),
		}

	ai_used = frappe.db.count(
		"TOB Bible Conversation Message", {"owner": user, "role": "user", "creation": [">=", nowdate()]}
	)
	translation_used = frappe.db.count(
		"TOB Translation Usage Log",
		{"user": user, "was_cache_hit": 0, "status": "success", "creation": [">=", nowdate()]},
	)
	tts_used = frappe.db.count(
		"TOB TTS Usage Log",
		{"user": user, "was_cache_hit": 0, "status": "success", "creation": [">=", nowdate()]},
	)
	return {
		"ai": status("ai", ai_used),
		"translation": status("translation", translation_used),
		"tts": status("tts", tts_used),
	}


_NOT_CHARGED = ChargeResult(charged=False, cost=0, free_remaining_today=None, wallet_balance=0)


def _gate(*, free_per_day, cost, used_today: int, out_of_free_message: str, balance: float) -> ChargeResult:
	"""Shared decision for all three features, once the caller has already
	established charging is enabled for this feature and this user isn't
	exempt. Never debits — callers only reach this once their own
	cache-hit check has already ruled out a free (uncharged) hit, and debit
	afterwards via record_*_charge, only once the underlying call actually
	succeeded."""
	free = int(free_per_day or 0)
	unit_cost = float(cost or 0)
	paid = used_today >= free
	if paid and balance < unit_cost:
		frappe.throw(_(out_of_free_message), frappe.ValidationError)

	remaining = max(0, free - used_today - (0 if paid else 1))
	return ChargeResult(
		charged=paid,
		cost=unit_cost if paid else 0,
		free_remaining_today=remaining,
		wallet_balance=balance - unit_cost if paid else balance,
	)


# --- AI Q&A --------------------------------------------------------------


def charge_ai(fn):
	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		user = frappe.session.user
		enabled = frappe.db.get_single_value("TOB AI Settings", "ai_charge_enabled")
		if not enabled or user in ("Guest", "Administrator"):
			return fn(*args, **kwargs)

		settings = _settings("ai_free_per_day", "ai_cost")
		used = frappe.db.count(
			"TOB Bible Conversation Message", {"owner": user, "role": "user", "creation": [">=", nowdate()]}
		)
		result = _gate(
			free_per_day=settings["ai_free_per_day"],
			cost=settings["ai_cost"],
			used_today=used,
			out_of_free_message="You've used today's free questions. Earn points and convert them to wallet balance to ask more.",
			balance=engine.wallet_balance(user),
		)
		response = fn(*args, **kwargs)
		if result.charged:
			engine.wallet_spend(user, result.cost, "AI question", frappe.generate_hash(length=10))
		if isinstance(response, dict):
			response["usage"] = result._asdict()
		return response

	return wrapper


# --- Translation -----------------------------------------------------------


def charge_translation(user: str) -> ChargeResult:
	"""Call immediately before generating a translation (a confirmed cache
	miss — never on a hit). Raises if the user is out of free translations
	and can't afford one; otherwise returns the decision so the caller can
	attach a "usage" block and debit via record_translation_charge() once
	the generation succeeds. Returns a no-op result (never raises) when
	charging is off or the user is exempt, same as charge_ai's early exit."""
	enabled = frappe.db.get_single_value("TOB AI Settings", "translation_charge_enabled")
	if not enabled or user in ("Guest", "Administrator"):
		return _NOT_CHARGED

	settings = _settings("translation_free_per_day", "translation_cost")
	used = frappe.db.count(
		"TOB Translation Usage Log",
		{"user": user, "was_cache_hit": 0, "status": "success", "creation": [">=", nowdate()]},
	)
	return _gate(
		free_per_day=settings["translation_free_per_day"],
		cost=settings["translation_cost"],
		used_today=used,
		out_of_free_message="You've used today's free translations. Earn points and convert them to wallet balance to translate more.",
		balance=engine.wallet_balance(user),
	)


def record_translation_charge(user: str, result: ChargeResult, ref: str) -> None:
	if result.charged:
		engine.wallet_spend(user, result.cost, "Translation", ref)


# --- Premium Voice (TTS) ----------------------------------------------------


def charge_tts(user: str) -> ChargeResult:
	"""Same shape as charge_translation, for a confirmed TTS cache miss."""
	enabled = frappe.db.get_single_value("TOB AI Settings", "tts_charge_enabled")
	if not enabled or user in ("Guest", "Administrator"):
		return _NOT_CHARGED

	settings = _settings("tts_free_per_day", "tts_cost")
	used = frappe.db.count(
		"TOB TTS Usage Log",
		{"user": user, "was_cache_hit": 0, "status": "success", "creation": [">=", nowdate()]},
	)
	return _gate(
		free_per_day=settings["tts_free_per_day"],
		cost=settings["tts_cost"],
		used_today=used,
		out_of_free_message="You've used today's free Premium Voice listens. Earn points and convert them to wallet balance to listen more.",
		balance=engine.wallet_balance(user),
	)


def record_tts_charge(user: str, result: ChargeResult, ref: str) -> None:
	if result.charged:
		engine.wallet_spend(user, result.cost, "Premium Voice", ref)
