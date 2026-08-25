"""The one door every API endpoint calls to actually generate AI content —
mirrors qtt_platform.ai.service's own role (one layer above AiGateway,
still knows nothing about what a "quiz" or "verse explanation" is), minus
the credit reservation qtt_platform's generate_and_track() does: this site
has no billing system, so there's nothing to reserve or refund."""

from truth_of_bible.ai.bootstrap import build_registry
from truth_of_bible.ai.core.gateway import AiGateway
from truth_of_bible.ai.core.request import AiRequest
from truth_of_bible.ai.core.response import AiResponse
from truth_of_bible.ai.usage import record_usage


def generate(request: AiRequest) -> AiResponse:
	gateway = AiGateway(build_registry(), on_call=record_usage)
	return gateway.generate(request)
