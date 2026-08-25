"""Ported from qtt_platform.ai.core.response (read directly this session) —
the single response shape every AI-generating feature consumes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AiUsage:
	input_tokens: int | None = None
	output_tokens: int | None = None
	total_tokens: int | None = None


@dataclass(frozen=True)
class AiResponse:
	content: str
	usage: AiUsage
	provider: str
	model: str
	request_id: str
	duration_ms: int
	#: Raw provider payload, kept only for debugging/audit — business
	#: logic must never branch on this.
	raw_metadata: dict | None = None
