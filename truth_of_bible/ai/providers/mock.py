"""Ported from qtt_platform.ai.providers.mock (read directly this session)
— deterministic, network-free, always configured. Use this provider while
testing the gateway's own routing/retry/fallback logic, or the API layer
end-to-end, without spending money or needing a real key."""

import frappe

from truth_of_bible.ai.core.provider import AiCapabilities, AiProvider
from truth_of_bible.ai.core.request import AiRequest
from truth_of_bible.ai.core.response import AiResponse, AiUsage

PROVIDER_KEY = "mock"


class MockProvider(AiProvider):
	name = PROVIDER_KEY
	capabilities = AiCapabilities(structured_output=True)

	def is_configured(self) -> bool:
		return True

	def generate(self, request: AiRequest) -> AiResponse:
		content = (
			f'{{"mock": true, "task": "{request.task}", "language": "{request.language}"}}'
			if request.structured_output
			else f"Mock response for task '{request.task}' in language '{request.language}'"
		)
		return AiResponse(
			content=content,
			usage=AiUsage(input_tokens=10, output_tokens=10, total_tokens=20),
			provider=PROVIDER_KEY,
			model=request.model or "mock-model",
			request_id=frappe.generate_hash(length=12),
			duration_ms=1,
		)
