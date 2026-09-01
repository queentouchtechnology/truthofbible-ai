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

#: Error Log message / exception text is capped so a very large provider
#: error body (rare, but seen with some gateways/proxies) can't bloat the
#: Error Log or the TOB AI Usage Log row it ends up copied into.
_MAX_LOGGED_BODY_CHARS = 4000


def _describe_error(provider_name: str, endpoint: str, model: str, status_code: int, body: str) -> str:
	"""Secret-free summary of a failed provider call. Deliberately takes
	only the provider's response body (`body`) — never the request headers
	or api_key — so this can safely go into both the raised exception's
	message (which ends up in TOB AI Usage Log.error_message and in
	Frappe's error traceback) and the server-side Error Log, without ever
	risking a leaked credential."""
	safe_body = (body or "")[:_MAX_LOGGED_BODY_CHARS]
	return f"provider={provider_name} model={model} status={status_code} endpoint={endpoint}\n\n{safe_body}"


def _log_provider_error(provider_name: str, endpoint: str, model: str, status_code: int, body: str) -> str:
	"""Writes a searchable Frappe Error Log entry for a failed provider
	call and returns the same description to use as the exception message.
	Previously the raised AiProviderException carried only the raw
	response body — with no status code, model, or endpoint attached, a
	site admin reading the Error Log (or the generic 'Could not generate
	an explanation' ValidationError Flutter receives) had no way to tell
	*which* provider/model/endpoint failed or why, short of re-deriving it
	from a truncated traceback. A logging failure here must never mask the
	real provider error, so it's swallowed — matching AiGateway._record's
	same defensive pattern for its own on_call recorder."""
	description = _describe_error(provider_name, endpoint, model, status_code, body)
	try:
		frappe.log_error(title=f"AI provider error: {provider_name} ({status_code})", message=description)
	except Exception:
		pass
	return description


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

	endpoint = f"{base_url.rstrip('/')}/chat/completions"

	try:
		http_response = requests.post(
			endpoint,
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
		raise AiProviderException(
			"RateLimited",
			provider_name,
			_log_provider_error(provider_name, endpoint, request.model, http_response.status_code, http_response.text),
			is_transient=True,
		)
	if http_response.status_code >= 500:
		raise AiProviderException(
			"ProviderServerError",
			provider_name,
			_log_provider_error(provider_name, endpoint, request.model, http_response.status_code, http_response.text),
			is_transient=True,
		)
	if http_response.status_code >= 400:
		raise AiProviderException(
			"ProviderRequestError",
			provider_name,
			_log_provider_error(provider_name, endpoint, request.model, http_response.status_code, http_response.text),
			is_transient=False,
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
