"""BIR (Biblical Intelligence Rating) math — a standard Elo update. Pure
functions, no Frappe/DB dependency, so they're testable without a site.
Called once per completed battle from games/bible_battle/engine.py, which
owns reading/writing the actual TOB Bible Battle Rating documents.
"""

K_FACTOR = 32
STARTING_BIR = 1000
MIN_BIR = 100


def expected_score(bir_self: int, bir_opponent: int) -> float:
	"""Probability `bir_self` is expected to score against `bir_opponent`,
	the standard logistic Elo curve."""
	return 1 / (1 + 10 ** ((bir_opponent - bir_self) / 400))


def new_bir(bir_self: int, bir_opponent: int, actual_score: float) -> int:
	"""`actual_score` is 1 for a win, 0.5 for a draw, 0 for a loss. Larger
	rating gaps naturally produce smaller/larger swings (a big favorite
	beating a big underdog barely moves; an upset moves a lot) — this is
	what makes "1200 beats 800 -> small change, 1200 beats 1400 -> larger
	change" fall out of the formula rather than needing special-casing."""
	delta = K_FACTOR * (actual_score - expected_score(bir_self, bir_opponent))
	return max(MIN_BIR, round(bir_self + delta))


def apply_battle_result(bir_a: int, bir_b: int, outcome_a: float) -> tuple[int, int]:
	"""`outcome_a` is 1/0.5/0 from player A's perspective (B's is 1 - outcome_a
	for a win/loss, 0.5 for a draw). Returns (new_bir_a, new_bir_b)."""
	outcome_b = 1 - outcome_a if outcome_a != 0.5 else 0.5
	return new_bir(bir_a, bir_b, outcome_a), new_bir(bir_b, bir_a, outcome_b)
