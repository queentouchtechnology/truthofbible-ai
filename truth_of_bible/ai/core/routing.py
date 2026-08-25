"""Ported from qtt_platform.ai.core.routing (read directly this session) —
task -> (provider, model) resolution, sourced from TOB AI Model so
changing which model handles a task is a Desk UI edit, not a code deploy."""

import frappe
from frappe import _


def resolve_routing(task: str, requested_provider: str | None = None, requested_model: str | None = None) -> tuple[str, str]:
	"""Returns (provider_key, model_id). An explicit provider+model on the
	request always wins; otherwise looks up the TOB AI Model row whose
	default_for_task matches `task`, on an enabled provider."""
	if requested_provider and requested_model:
		return requested_provider, requested_model

	model_row = frappe.db.get_value(
		"TOB AI Model", {"default_for_task": task}, ["provider", "model_id"], as_dict=True
	)
	if not model_row:
		frappe.throw(_("No AI model configured for task '{0}'.").format(task))

	provider_enabled = frappe.db.get_value("TOB AI Provider", model_row.provider, "enabled")
	if not provider_enabled:
		frappe.throw(_("The provider configured for task '{0}' is disabled.").format(task))

	return model_row.provider, model_row.model_id


def resolve_fallback_provider(exclude: str) -> str | None:
	"""The provider flagged is_fallback=1, if any, and enabled, and not
	the same provider that just failed."""
	fallback = frappe.db.get_value("TOB AI Provider", {"is_fallback": 1, "enabled": 1}, "name")
	if not fallback or fallback == exclude:
		return None
	return fallback


def resolve_default_model_for_provider(provider: str) -> str | None:
	"""Used when falling back to a provider with no task-specific model
	mapping — picks any TOB AI Model row registered for that provider."""
	return frappe.db.get_value("TOB AI Model", {"provider": provider}, "model_id")
