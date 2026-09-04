"""Pure-function tests for matchmaking BIR-tolerance math — no Frappe/DB
dependency. Covers spec §32's matchmaking-compatibility cases and §6's
"a strong player shouldn't instantly grab a beginner" rule.
"""

import unittest

from truth_of_bible.games.bible_battle.matchmaking_rules import is_compatible, tolerance_for


class TestToleranceFor(unittest.TestCase):
	def test_fresh_wait_is_tightest_tier(self):
		self.assertEqual(tolerance_for(0), 100)

	def test_widens_after_15_seconds(self):
		self.assertEqual(tolerance_for(20), 200)

	def test_widens_further_after_30_seconds(self):
		self.assertEqual(tolerance_for(31), 300)

	def test_caps_at_widest_tier(self):
		self.assertEqual(tolerance_for(10_000), 300)


class TestIsCompatible(unittest.TestCase):
	def test_close_bir_fresh_players_match(self):
		self.assertTrue(is_compatible(1000, 1050, 0, 0))

	def test_far_bir_fresh_players_do_not_match(self):
		self.assertFalse(is_compatible(1000, 1500, 0, 0))

	def test_far_bir_matches_once_both_have_waited_long_enough(self):
		self.assertTrue(is_compatible(1000, 1250, 40, 40))

	def test_strong_player_cannot_instantly_grab_a_long_waiting_beginner(self):
		# A beginner has waited 60s (tolerance 300 on their side), but the
		# strong player just joined (tolerance 100 on theirs) — the match
		# must use the STRICTER of the two, so a 300-point gap still fails.
		self.assertFalse(is_compatible(1000, 1300, 0, 60))

	def test_symmetric_regardless_of_argument_order(self):
		self.assertEqual(
			is_compatible(1000, 1300, 0, 60),
			is_compatible(1300, 1000, 60, 0),
		)


if __name__ == "__main__":
	unittest.main()
