"""Cost estimation against TOB AI Model's own cost_input_per_1m/
cost_output_per_1m fields — an admin-editable price table, not a hardcoded
one, matching qtt_platform's cost_service reasoning (verified live this
session that pricing lives on the Model doctype, not in Python)."""

import frappe


def estimate_cost_usd(provider: str, model: str, usage) -> float:
	if usage is None:
		return 0

	row = frappe.db.get_value(
		"TOB AI Model",
		{"provider": provider, "model_id": model},
		["cost_input_per_1m", "cost_output_per_1m"],
		as_dict=True,
	)
	if not row:
		return 0

	input_cost = (usage.input_tokens or 0) / 1_000_000 * (row.cost_input_per_1m or 0)
	output_cost = (usage.output_tokens or 0) / 1_000_000 * (row.cost_output_per_1m or 0)
	return round(input_cost + output_cost, 6)
