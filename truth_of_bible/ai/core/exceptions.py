"""Ported from qtt_platform.ai.core.exceptions (read directly this session)
— identical shape, this app's own AI gateway is independent code, not an
import of qtt_platform."""


class AiProviderException(Exception):
	def __init__(
		self,
		kind: str,
		provider: str,
		message: str,
		cause: Exception | None = None,
		*,
		is_transient: bool = False,
		is_fallback_eligible: bool = True,
	):
		super().__init__(message)
		self.kind = kind
		self.provider = provider
		self.cause = cause
		self.is_transient = is_transient
		self.is_fallback_eligible = is_fallback_eligible


class ProviderNotConfigured(AiProviderException):
	"""Raised when a provider's is_configured() is False — a missing API
	key or a disabled TOB AI Provider row. Fallback-eligible (a different
	provider might be configured) but not transient (retrying the same
	unconfigured provider will never succeed)."""

	def __init__(self, provider: str):
		super().__init__(
			"ProviderNotConfigured",
			provider,
			f"{provider} is not configured",
			is_transient=False,
			is_fallback_eligible=True,
		)
