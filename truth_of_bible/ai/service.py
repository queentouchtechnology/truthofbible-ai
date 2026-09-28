"""The one door every API endpoint calls to actually generate AI content —
mirrors qtt_platform.ai.service's own role (one layer above AiGateway,
still knows nothing about what a "quiz" or "verse explanation" is), minus
the credit reservation qtt_platform's generate_and_track() does: this site
has no billing system, so there's nothing to reserve or refund.

Being the one door also makes this the one place to enforce
TOB AI Settings' access controls (ai_enabled + blocked_users) — every
feature built on top (explanations, Q&A, quizzes, translation) gets the
global kill switch and per-user restriction for free, with no per-endpoint
changes, because they all already call generate()."""

import frappe

from truth_of_bible.ai.bootstrap import build_registry
from truth_of_bible.ai.core.exceptions import AiProviderException
from truth_of_bible.ai.core.gateway import AiGateway
from truth_of_bible.ai.core.request import AiRequest
from truth_of_bible.ai.core.response import AiResponse
from truth_of_bible.ai.usage import record_usage


class AiAccessDisabled(AiProviderException):
	"""Raised before any provider is even chosen — never transient (no
	amount of retrying changes an admin's setting) and not
	fallback-eligible (every provider is gated by the same check)."""

	def __init__(self, message: str):
		super().__init__("AiAccessDisabled", "system", message, is_transient=False, is_fallback_eligible=False)


def _ai_globally_enabled() -> bool:
	value = frappe.db.get_single_value("TOB AI Settings", "ai_enabled")
	return True if value is None else bool(value)


def _user_is_blocked(user: str | None) -> bool:
	if not user or user == "Guest":
		return False
	return bool(frappe.db.exists("TOB AI Blocked User", {"parent": "TOB AI Settings", "user": user}))


def _enforce_access():
	if not _ai_globally_enabled():
		raise AiAccessDisabled("AI features are currently turned off.")
	if _user_is_blocked(frappe.session.user):
		raise AiAccessDisabled("AI features have been turned off for your account.")


def generate(request: AiRequest) -> AiResponse:
	_enforce_access()
	gateway = AiGateway(build_registry(), on_call=record_usage)
	return gateway.generate(request)
