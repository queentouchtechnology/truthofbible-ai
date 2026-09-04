"""Pure-function tests for answer scoring — no Frappe/DB dependency.
Covers spec §32's "Scoring" cases (correct/speed bonus/wrong/no-answer)."""

import unittest

from truth_of_bible.games.bible_battle.scoring import (
	ANSWER_GRACE_MS,
	ANSWER_WINDOW_MS,
	points_for,
	speed_bonus,
	within_window,
)


class TestWithinWindow(unittest.TestCase):
	def test_instant_answer_is_within_window(self):
		self.assertTrue(within_window(0))

	def test_answer_right_at_window_edge_is_within_window(self):
		self.assertTrue(within_window(ANSWER_WINDOW_MS))

	def test_answer_within_grace_period_is_within_window(self):
		self.assertTrue(within_window(ANSWER_WINDOW_MS + ANSWER_GRACE_MS))

	def test_answer_past_grace_period_is_not_within_window(self):
		self.assertFalse(within_window(ANSWER_WINDOW_MS + ANSWER_GRACE_MS + 1))


class TestSpeedBonus(unittest.TestCase):
	def test_instant_answer_gets_max_bonus(self):
		self.assertEqual(speed_bonus(0), 50)

	def test_answer_at_window_edge_gets_no_bonus(self):
		self.assertEqual(speed_bonus(ANSWER_WINDOW_MS), 0)

	def test_answer_halfway_gets_half_bonus(self):
		self.assertEqual(speed_bonus(ANSWER_WINDOW_MS // 2), 25)

	def test_bonus_never_negative_past_the_window(self):
		self.assertEqual(speed_bonus(ANSWER_WINDOW_MS + 5000), 0)


class TestPointsFor(unittest.TestCase):
	def test_correct_instant_answer_gets_base_plus_full_bonus(self):
		self.assertEqual(points_for(True, 0), 150)

	def test_correct_slow_answer_gets_base_only(self):
		self.assertEqual(points_for(True, ANSWER_WINDOW_MS), 100)

	def test_wrong_answer_gets_zero_regardless_of_speed(self):
		self.assertEqual(points_for(False, 0), 0)

	def test_no_answer_gets_zero(self):
		# submit_answer treats "no selected_option" as is_correct=False.
		self.assertEqual(points_for(False, ANSWER_WINDOW_MS + ANSWER_GRACE_MS + 1), 0)


if __name__ == "__main__":
	unittest.main()
