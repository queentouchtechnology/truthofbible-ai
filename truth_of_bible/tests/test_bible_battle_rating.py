"""Pure-function tests for BIR (Elo) math — no Frappe/DB dependency, so
these run fast and don't need a site. Covers spec §32's "Rating" cases.
"""

import unittest

from truth_of_bible.games.bible_battle.rating import apply_battle_result, expected_score, new_bir


class TestExpectedScore(unittest.TestCase):
	def test_equal_ratings_expect_half(self):
		self.assertAlmostEqual(expected_score(1000, 1000), 0.5)

	def test_higher_rating_expects_more_than_half(self):
		self.assertGreater(expected_score(1400, 1000), 0.5)

	def test_lower_rating_expects_less_than_half(self):
		self.assertLess(expected_score(1000, 1400), 0.5)


class TestNewBir(unittest.TestCase):
	def test_win_increases_rating(self):
		self.assertGreater(new_bir(1000, 1000, 1.0), 1000)

	def test_loss_decreases_rating(self):
		self.assertLess(new_bir(1000, 1000, 0.0), 1000)

	def test_draw_near_equal_ratings_barely_moves(self):
		self.assertEqual(new_bir(1000, 1000, 0.5), 1000)

	def test_underdog_win_gains_more_than_favorite_win(self):
		# 1000 beating 1400 (a big upset) should gain more than 1000 beating
		# 1000 (an even match) — spec §14's worked example, generalized.
		upset_gain = new_bir(1000, 1400, 1.0) - 1000
		even_gain = new_bir(1000, 1000, 1.0) - 1000
		self.assertGreater(upset_gain, even_gain)

	def test_favorite_beating_underdog_gains_little(self):
		# 1400 beating 1000 (expected outcome) should gain less than an even match.
		favorite_gain = new_bir(1400, 1000, 1.0) - 1400
		even_gain = new_bir(1000, 1000, 1.0) - 1000
		self.assertLess(favorite_gain, even_gain)

	def test_rating_floor_is_respected(self):
		self.assertGreaterEqual(new_bir(100, 2000, 0.0), 100)


class TestApplyBattleResult(unittest.TestCase):
	def test_winner_gains_loser_loses(self):
		new_a, new_b = apply_battle_result(1000, 1000, 1.0)
		self.assertGreater(new_a, 1000)
		self.assertLess(new_b, 1000)

	def test_draw_both_near_unchanged_when_equal(self):
		new_a, new_b = apply_battle_result(1000, 1000, 0.5)
		self.assertEqual(new_a, 1000)
		self.assertEqual(new_b, 1000)

	def test_1200_beats_800_small_change(self):
		new_a, _ = apply_battle_result(1200, 800, 1.0)
		self.assertLess(new_a - 1200, 10)

	def test_1200_beats_1400_larger_change(self):
		new_a, _ = apply_battle_result(1200, 1400, 1.0)
		self.assertGreater(new_a - 1200, 10)


if __name__ == "__main__":
	unittest.main()
