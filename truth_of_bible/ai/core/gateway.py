"""Ported from qtt_platform.ai.core.gateway (read directly this session) —
the one door into the AI system. Callers call gateway.generate(request)
and never touch a provider directly. Owns: provider/model routing, retry,
fallback, response/error normalization, and a hook for usage/cost
recording. Deliberately has ZERO knowledge of what a "verse explanation"
or "quiz" is — that lives in truth_of_bible/api/, one layer up."""

from typing import Callable

import frappe

from truth_of_bible.ai.core.exceptions import AiProviderException
from truth_of_bible.ai.core.registry import AiProviderRegistry
from truth_of_bible.ai.core.request import AiRequest
from truth_of_bible.ai.core.response import AiResponse
from truth_of_bible.ai.core.routing import (
	resolve_default_model_for_provider,
	resolve_fallback_provider,
	resolve_routing,
)

#: Deliberately no backoff delay — favor fast fallback over slow
#: same-provider retries, matching qtt_platform's own reasoning.
DEFAULT_MAX_RETRIES = 1

#: (request, response|None, error|None, attempted_provider, attempted_model,
#:  was_fallback) -> None
UsageRecorder = Callable[..., None]


class AiGateway:
	def __init__(self, registry: AiProviderRegistry, *, max_retries: int = DEFAULT_MAX_RETRIES, on_call: UsageRecorder | None = None):
		self.registry = registry
		self.max_retries = max_retries
		self.on_call = on_call

	def generate(self, request: AiRequest) -> AiResponse:
		provider_name, model_id = resolve_routing(request.task, request.provider, request.model)
		request_for_provider = request.with_model(model_id)

		try:
			response = self._call_with_retry(provider_name, request_for_provider)
			self._record(request, response=response, provider=provider_name, model=model_id, was_fallback=False)
			return response
		except AiProviderException as primary_error:
			self._record(request, error=primary_error, provider=provider_name, model=model_id, was_fallback=False)

			fallback_provider = resolve_fallback_provider(exclude=provider_name)
			if not fallback_provider or not primary_error.is_fallback_eligible:
				raise primary_error

			fallback_model = resolve_default_model_for_provider(fallback_provider) or model_id
			fallback_request = request.with_model(fallback_model)

			try:
				response = self._call_with_retry(fallback_provider, fallback_request)
				self._record(request, response=response, provider=fallback_provider, model=fallback_model, was_fallback=True)
				return response
			except AiProviderException as fallback_error:
				self._record(request, error=fallback_error, provider=fallback_provider, model=fallback_model, was_fallback=True)
				# Surface the primary failure — it's usually more actionable
				# than the fallback's own failure.
				raise primary_error

	def _call_with_retry(self, provider_name: str, request: AiRequest) -> AiResponse:
		provider = self.registry.resolve(provider_name)
		last_error: AiProviderException | None = None

		for attempt in range(self.max_retries + 1):
			try:
				return provider.generate(request)
			except AiProviderException as error:
				last_error = error
				if not error.is_transient or attempt == self.max_retries:
					raise error
			except Exception as exc:
				error = AiProviderException("UnknownProviderError", provider_name, str(exc), exc)
				last_error = error
				raise error

		raise last_error  # unreachable — loop above always returns or raises

	def _record(self, request, *, response=None, error=None, provider: str, model: str, was_fallback: bool):
		if self.on_call:
			try:
				self.on_call(
					request=request, response=response, error=error,
					attempted_provider=provider, attempted_model=model, was_fallback=was_fallback,
				)
			except Exception:
				# A usage-recording failure must never mask the real
				# generate()/error outcome — log and move on.
				frappe.log_error(title="Truth of Bible AI gateway on_call recorder failed", message=frappe.get_traceback())
