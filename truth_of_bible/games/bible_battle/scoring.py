"""Pure answer-scoring math — no Frappe/DB dependency, testable without a
site. engine.py owns reading/writing the actual Answer/Battle documents;
this only turns a response time into a point value.
"""

ANSWER_WINDOW_MS = 10_000
ANSWER_GRACE_MS = 500
SPEED_BONUS_MAX = 50
BASE_POINTS = 100


def within_window(response_time_ms: int) -> bool:
	return response_time_ms <= ANSWER_WINDOW_MS + ANSWER_GRACE_MS


def speed_bonus(response_time_ms: int) -> int:
	"""Linear decay from 50 down to 0 across the 10s window."""
	return round(SPEED_BONUS_MAX * max(0, (ANSWER_WINDOW_MS - response_time_ms) / ANSWER_WINDOW_MS))


def points_for(is_correct: bool, response_time_ms: int) -> int:
	if not is_correct:
		return 0
	return BASE_POINTS + speed_bonus(response_time_ms)
