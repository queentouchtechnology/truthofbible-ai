"""Pure matchmaking-tolerance math — no Frappe/DB dependency, testable
without a site. matchmaking.py owns the actual queue scan/claim; this only
answers "are these two BIRs, given how long each has waited, compatible?"
"""

#: Tolerance widens the longer a candidate has been waiting. A match only
#: happens if the gap fits BOTH sides' current tolerance (the stricter of
#: the two) — a fresh caller's own tolerance is always the first tier
#: (elapsed 0s), which is what stops a strong player instantly grabbing a
#: beginner who has been waiting a long time (spec §6).
TOLERANCE_TIERS = ((15, 100), (30, 200), (float("inf"), 300))

#: A Searching row this old is treated as an abandoned/crashed client and
#: opportunistically cancelled when encountered during a scan — a
#: leak-prevention safety net, not an active "give up" policy.
STALE_QUEUE_SECONDS = 120


def tolerance_for(elapsed_seconds: float) -> int:
	for threshold, tolerance in TOLERANCE_TIERS:
		if elapsed_seconds < threshold:
			return tolerance
	return TOLERANCE_TIERS[-1][1]


def is_compatible(bir_a: int, bir_b: int, elapsed_seconds_a: float, elapsed_seconds_b: float) -> bool:
	allowed = min(tolerance_for(elapsed_seconds_a), tolerance_for(elapsed_seconds_b))
	return abs(bir_a - bir_b) <= allowed
