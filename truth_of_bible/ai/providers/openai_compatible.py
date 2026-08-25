"""Ported from qtt_platform.ai.providers.openai_compatible (read directly
this session) — the shared HTTP client for every provider whose wire
format is the standard OpenAI chat completions shape (DeepSeek, OpenAI,
OpenRouter). Synchronous `requests`, matching Frappe's WSGI worker model
(no event loop)."""

import time

import frappe
import requests

from truth_of_bible.ai.core.exceptions import AiProviderException
from truth_of_bible.ai.core.request import AiRequest
from truth_of_bible.ai.core.response import AiResponse, AiUsage

DEFAULT_TIMEOUT_SECONDS = 60


def call_openai_compatible_chat(
	*,
	base_url: str,
	api_key: str,
	provider_name: str,
	request: AiRequest,
	timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> AiResponse:
	start = time.monotonic()
	payload: dict = {
		"model": request.model,
		"messages": [{"role": m.role, "content": m.content} for m in request.messages],
	}
	if request.temperature is not None:
		payload["temperature"] = request.temperature
	if request.max_output_tokens is not None:
		payload["max_tokens"] = request.max_output_tokens
	if request.structured_output:
		payload["response_format"] = {"type": "json_object"}

	try:
		http_response = requests.post(
			f"{base_url.rstrip('/')}/chat/completions",
			headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
			json=payload,
			timeout=timeout,
		)
	except requests.Timeout as exc:
		raise AiProviderException(
			"Timeout", provider_name, "Request timed out", exc, is_transient=True
		) from exc
	except requests.RequestException as exc:
		raise AiProviderException("NetworkError", provider_name, str(exc), exc, is_transient=True) from exc

	duration_ms = int((time.monotonic() - start) * 1000)

	if http_response.status_code == 429:
		raise AiProviderException("RateLimited", provider_name, "Rate limited", is_transient=True)
	if http_response.status_code >= 500:
		raise AiProviderException(
			"ProviderServerError", provider_name, http_response.text, is_transient=True
		)
	if http_response.status_code >= 400:
		raise AiProviderException(
			"ProviderRequestError", provider_name, http_response.text, is_transient=False
		)

	data = http_response.json()
	choice = data["choices"][0]
	usage_raw = data.get("usage") or {}

	return AiResponse(
		content=choice["message"]["content"],
		usage=AiUsage(
			input_tokens=usage_raw.get("prompt_tokens"),
			output_tokens=usage_raw.get("completion_tokens"),
			total_tokens=usage_raw.get("total_tokens"),
		),
		provider=provider_name,
		model=request.model,
		request_id=data.get("id") or frappe.generate_hash(length=12),
		duration_ms=duration_ms,
		raw_metadata={"finish_reason": choice.get("finish_reason")},
	)
