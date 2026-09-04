"""Integration + security tests for Bible Battle. Requires a real Frappe
site (run via `bench --site <site> run-tests --app truth_of_bible`) — not
runnable standalone like the pure-function test_bible_battle_*.py files,
since it exercises real DocType permission checks and DB state.

Covers two things explicitly requested in review:
1. The REST-lockdown guarantee: `frappe.client.get`/`get_list`/`set_value`
   (the literal functions `/api/resource/...` dispatches to) must reject a
   normal authenticated player for all five Bible Battle doctypes — even a
   battle's own participants, per the "no ownership-based grant" design in
   the plan (TOB Bible Battle.question_sequence holds future questions).
2. The whitelisted API path still works end-to-end despite that lockdown
   (a positive control — the closure above must not also break real play),
   plus the core anti-cheat rules from spec §32 (can't answer for another
   player, can't resubmit, can't answer a stale/wrong question).
"""

import frappe
from frappe.client import get as client_get
from frappe.client import get_list as client_get_list
from frappe.client import set_value as client_set_value
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from truth_of_bible.games.bible_battle import engine
from truth_of_bible.games.bible_battle.utils import get_or_create_rating

USER_A = "bible-battle-test-a@example.com"
USER_B = "bible-battle-test-b@example.com"
OUTSIDER = "bible-battle-test-outsider@example.com"


def _ensure_test_user(email: str) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	return email


class TestBibleBattleSecurity(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.user_a = _ensure_test_user(USER_A)
		cls.user_b = _ensure_test_user(USER_B)
		cls.outsider = _ensure_test_user(OUTSIDER)

	def setUp(self):
		frappe.set_user("Administrator")
		self.battle = frappe.get_doc(
			{
				"doctype": "TOB Bible Battle",
				"player_1": self.user_a,
				"player_2": self.user_b,
				"status": "Waiting",
			}
		)
		self.battle.insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _play_full_battle(self):
		"""Drives one complete battle through only the whitelisted engine
		functions — the positive control the REST-lockdown tests need."""
		engine.set_ready(self.battle.name, self.user_a)
		engine.set_ready(self.battle.name, self.user_b)
		for _ in range(10):
			question = engine.get_current_question(self.battle.name, self.user_a)
			engine.submit_answer(self.battle.name, question["question"], "A", self.user_a)
			engine.submit_answer(self.battle.name, question["question"], "A", self.user_b)
		return frappe.get_doc("TOB Bible Battle", self.battle.name)

	# --- Positive control: the legitimate path still works ----------------

	def test_full_battle_completes_via_whitelisted_api_only(self):
		finished = self._play_full_battle()
		self.assertEqual(finished.status, "Completed")
		self.assertIsNotNone(finished.winner)
		self.assertIsNotNone(finished.player_1_bir_after)
		self.assertIsNotNone(finished.player_2_bir_after)

	# --- REST lockdown (explicit review requirement) -----------------------

	def test_player_a_cannot_read_own_battle_via_rest(self):
		# Deliberately not owner-scoped: question_sequence holds FUTURE
		# question ids, so even a legitimate participant is blocked.
		frappe.set_user(self.user_a)
		with self.assertRaises(frappe.PermissionError):
			client_get("TOB Bible Battle", self.battle.name)

	def test_outsider_cannot_read_battle_via_rest(self):
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			client_get("TOB Bible Battle", self.battle.name)

	def test_player_cannot_list_answers_via_rest(self):
		frappe.set_user("Administrator")
		question_name = frappe.db.get_value("TOB Bible Battle Question", {"status": "Published"}, "name")
		frappe.get_doc(
			{
				"doctype": "TOB Bible Battle Answer",
				"battle": self.battle.name,
				"player": self.user_b,
				"question": question_name,
				"question_index": 1,
				"selected_option": "A",
				"answered_at": now_datetime(),
			}
		).insert(ignore_permissions=True)

		frappe.set_user(self.user_a)
		with self.assertRaises(frappe.PermissionError):
			client_get_list("TOB Bible Battle Answer", filters={"battle": self.battle.name})

	def test_player_cannot_modify_battle_via_rest(self):
		frappe.set_user(self.user_a)
		with self.assertRaises(frappe.PermissionError):
			client_set_value("TOB Bible Battle", self.battle.name, "player_1_score", 9999)

	def test_player_cannot_modify_rating_via_rest(self):
		frappe.set_user("Administrator")
		get_or_create_rating(self.user_a)
		frappe.set_user(self.user_a)
		with self.assertRaises(frappe.PermissionError):
			client_set_value("TOB Bible Battle Rating", self.user_a, "bir", 9999)

	def test_player_cannot_read_question_bank_via_rest(self):
		frappe.set_user("Administrator")
		question_name = frappe.db.get_value("TOB Bible Battle Question", {"status": "Published"}, "name")

		frappe.set_user(self.user_a)
		with self.assertRaises(frappe.PermissionError):
			client_get("TOB Bible Battle Question", question_name)
		with self.assertRaises(frappe.PermissionError):
			client_get_list("TOB Bible Battle Question")

	# --- Core anti-cheat rules (spec §32) ----------------------------------

	def test_non_participant_cannot_submit_answer(self):
		engine.set_ready(self.battle.name, self.user_a)
		engine.set_ready(self.battle.name, self.user_b)
		question = engine.get_current_question(self.battle.name, self.user_a)
		with self.assertRaises(frappe.PermissionError):
			engine.submit_answer(self.battle.name, question["question"], "A", self.outsider)

	def test_duplicate_answer_is_rejected(self):
		engine.set_ready(self.battle.name, self.user_a)
		engine.set_ready(self.battle.name, self.user_b)
		question = engine.get_current_question(self.battle.name, self.user_a)
		engine.submit_answer(self.battle.name, question["question"], "A", self.user_a)
		with self.assertRaises(frappe.ValidationError):
			engine.submit_answer(self.battle.name, question["question"], "B", self.user_a)

	def test_answer_to_non_current_question_is_rejected(self):
		engine.set_ready(self.battle.name, self.user_a)
		engine.set_ready(self.battle.name, self.user_b)
		# Any Published question other than the battle's actual current one.
		current = engine.get_current_question(self.battle.name, self.user_a)
		other_question = frappe.db.get_value(
			"TOB Bible Battle Question",
			{"status": "Published", "name": ["!=", current["question"]]},
			"name",
		)
		with self.assertRaises(frappe.ValidationError):
			engine.submit_answer(self.battle.name, other_question, "A", self.user_a)

	def test_cannot_ready_up_twice_into_a_second_battle_start(self):
		engine.set_ready(self.battle.name, self.user_a)
		engine.set_ready(self.battle.name, self.user_b)
		with self.assertRaises(frappe.ValidationError):
			engine.set_ready(self.battle.name, self.user_a)
