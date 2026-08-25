"""The AiGateway's `on_call` recorder — writes one TOB AI Usage Log row per
generation attempt. Unlike qtt_platform's usage_service, this has no
tenant/product/credit dimension at all: this site has no billing system,
so this is pure observability, not a gate anything else depends on."""

import frappe

from truth_of_bible.ai.services.cost import estimate_cost_usd


def record_usage(*, request, response=None, error=None, attempted_provider: str, attempted_model: str, was_fallback: bool):
	status = "success" if response is not None else "error"
	usage = response.usage if response is not None else None

	frappe.get_doc(
		{
			"doctype": "TOB AI Usage Log",
			"user": frappe.session.user,
			"task": request.task,
			"language": request.language,
			"provider": attempted_provider,
			"model": attempted_model,
			"was_fallback": 1 if was_fallback else 0,
			"input_tokens": usage.input_tokens if usage else None,
			"output_tokens": usage.output_tokens if usage else None,
			"total_tokens": usage.total_tokens if usage else None,
			"estimated_cost_usd": estimate_cost_usd(attempted_provider, attempted_model, usage) if usage else 0,
			"status": status,
			"duration_ms": response.duration_ms if response is not None else None,
			"error_message": str(error) if error is not None else None,
		}
	).insert(ignore_permissions=True)
