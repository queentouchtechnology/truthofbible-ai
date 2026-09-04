"""The battle engine: ready-up, question delivery, answer validation and
scoring, question advancement, forfeit detection, and finalization
(including the BIR update). The server is authoritative for all of this —
see the plan's "never trust the client" rule (§19 of the original spec).

check_and_advance() is the single source of truth for "should this battle
move to the next question / finish now" and is called from every
battle-scoped whitelisted method (get_current_question, submit_answer,
get_battle_status) plus the scheduler_events cron backstop in hooks.py —
never reimplemented per call site.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, time_diff_in_seconds

from truth_of_bible.games.bible_battle import rating as rating_module
from truth_of_bible.games.bible_battle.scoring import ANSWER_GRACE_MS, ANSWER_WINDOW_MS, points_for, within_window
from truth_of_bible.games.bible_battle.utils import (
	decode_question_sequence,
	encode_question_sequence,
	get_or_create_rating,
	opponent_slot,
	require_participant,
	select_question_sequence,
	touch_last_seen,
	user_display,
)

#: How long a player's last-seen timestamp can go stale before they're
#: treated as disconnected for forfeit purposes (§20).
FORFEIT_SECONDS = 60


def load_battle(battle_name: str, user: str):
	"""Every battle-scoped API entry point starts here: load, verify the
	caller is actually a participant (PermissionError otherwise), and mark
	them as freshly seen. Returns (battle_doc, 'player_1'|'player_2')."""
	battle = frappe.get_doc("TOB Bible Battle", battle_name)
	slot = require_participant(battle, user)
	touch_last_seen(battle, slot)
	return battle, slot


def set_ready(battle_name: str, user: str) -> dict:
	battle, slot = load_battle(battle_name, user)
	if battle.status != "Waiting":
		frappe.throw(_("This battle is not waiting for players to ready up."))

	battle.set(f"{slot}_ready", 1)
	if battle.player_1_ready and battle.player_2_ready:
		_begin_battle(battle)

	battle.save(ignore_permissions=True)
	return battle_state(battle, slot)


def _begin_battle(battle) -> None:
	sequence = select_question_sequence()
	battle.question_sequence = encode_question_sequence(sequence)
	battle.total_questions = len(sequence)
	battle.current_question_index = 1
	battle.question_start_time = now_datetime()
	battle.started_at = now_datetime()
	battle.status = "In Progress"


def get_current_question(battle_name: str, user: str) -> dict:
	battle, slot = load_battle(battle_name, user)
	check_and_advance(battle)
	battle.save(ignore_permissions=True)

	if battle.status != "In Progress":
		return battle_state(battle, slot)

	sequence = decode_question_sequence(battle.question_sequence)
	question_name = sequence[battle.current_question_index - 1]
	question = frappe.get_doc("TOB Bible Battle Question", question_name)

	return {
		"battle": battle.name,
		"question": question.name,
		"question_index": battle.current_question_index,
		"total_questions": battle.total_questions,
		"text": question.question,
		"options": {
			"A": question.option_a,
			"B": question.option_b,
			"C": question.option_c,
			"D": question.option_d,
		},
		"difficulty": question.difficulty,
		"remaining_ms": _remaining_ms(battle),
	}


def submit_answer(battle_name: str, question_name: str, selected_option: str | None, user: str) -> dict:
	battle, slot = load_battle(battle_name, user)
	check_and_advance(battle)

	if battle.status != "In Progress":
		battle.save(ignore_permissions=True)
		frappe.throw(_("This battle is not currently in progress."))

	sequence = decode_question_sequence(battle.question_sequence)
	current_question = sequence[battle.current_question_index - 1]
	if question_name != current_question:
		battle.save(ignore_permissions=True)
		frappe.throw(_("That is not the current question."))

	if frappe.db.exists(
		"TOB Bible Battle Answer",
		{"battle": battle.name, "player": user, "question": question_name},
	):
		battle.save(ignore_permissions=True)
		frappe.throw(_("You have already answered this question."))

	now = now_datetime()
	response_time_ms = int(time_diff_in_seconds(now, battle.question_start_time) * 1000)
	answered_in_time = within_window(response_time_ms)

	question = frappe.get_doc("TOB Bible Battle Question", question_name)
	is_correct = bool(answered_in_time and selected_option and selected_option == question.correct_option)
	points = points_for(is_correct, response_time_ms)

	frappe.get_doc(
		{
			"doctype": "TOB Bible Battle Answer",
			"battle": battle.name,
			"player": user,
			"question": question_name,
			"question_index": battle.current_question_index,
			"selected_option": selected_option if answered_in_time else None,
			"is_correct": 1 if is_correct else 0,
			"response_time_ms": response_time_ms,
			"points": points,
			"answered_at": now,
		}
	).insert(ignore_permissions=True)

	battle.set(f"{slot}_score", (battle.get(f"{slot}_score") or 0) + points)

	check_and_advance(battle)
	battle.save(ignore_permissions=True)

	opponent = battle.get(opponent_slot(slot))
	frappe.publish_realtime(
		"bible_battle_opponent_answered",
		{"battle": battle.name, "question_index": current_question},
		user=opponent,
	)
	if battle.status == "Completed":
		for participant in (battle.player_1, battle.player_2):
			frappe.publish_realtime("bible_battle_completed", {"battle": battle.name}, user=participant)

	return {
		"is_correct": is_correct,
		"points": points,
		"correct_option": question.correct_option,
		"explanation": question.explanation,
		"reference": question.reference,
	}


def get_battle_status(battle_name: str, user: str) -> dict:
	battle, slot = load_battle(battle_name, user)
	check_and_advance(battle)
	battle.save(ignore_permissions=True)
	return battle_state(battle, slot)


def get_battle_result(battle_name: str, user: str) -> dict:
	battle, slot = load_battle(battle_name, user)
	check_and_advance(battle)
	battle.save(ignore_permissions=True)

	if battle.status not in ("Completed", "Abandoned"):
		frappe.throw(_("This battle has not finished yet."))

	opp_slot = opponent_slot(slot)
	answers = frappe.get_all(
		"TOB Bible Battle Answer",
		filters={"battle": battle.name, "player": user},
		fields=["is_correct"],
	)
	correct_count = sum(1 for a in answers if a.is_correct)

	return {
		"battle": battle.name,
		"status": battle.status,
		"did_i_win": bool(battle.winner) and battle.winner == user,
		"winner": battle.winner,
		"my_score": battle.get(f"{slot}_score"),
		"opponent_score": battle.get(f"{opp_slot}_score"),
		"opponent": user_display(battle.get(opp_slot)),
		"total_questions": battle.total_questions,
		"correct_count": correct_count,
		"wrong_count": max(0, len(answers) - correct_count),
		"my_bir_before": battle.get(f"{slot}_bir_before"),
		"my_bir_after": battle.get(f"{slot}_bir_after"),
	}


def get_battle_history(user: str, limit: int = 20) -> list[dict]:
	rows = frappe.get_all(
		"TOB Bible Battle",
		filters=[["status", "in", ["Completed", "Abandoned"]], ["player_1", "=", user]],
		fields=[
			"name", "status", "player_1", "player_2", "player_1_score", "player_2_score",
			"winner", "completed_at", "player_1_bir_before", "player_1_bir_after",
			"player_2_bir_before", "player_2_bir_after",
		],
	) + frappe.get_all(
		"TOB Bible Battle",
		filters=[["status", "in", ["Completed", "Abandoned"]], ["player_2", "=", user]],
		fields=[
			"name", "status", "player_1", "player_2", "player_1_score", "player_2_score",
			"winner", "completed_at", "player_1_bir_before", "player_1_bir_after",
			"player_2_bir_before", "player_2_bir_after",
		],
	)
	rows.sort(key=lambda r: r.completed_at or "", reverse=True)

	history = []
	for row in rows[:limit]:
		is_p1 = row.player_1 == user
		history.append(
			{
				"battle": row.name,
				"status": row.status,
				"did_i_win": bool(row.winner) and row.winner == user,
				"my_score": row.player_1_score if is_p1 else row.player_2_score,
				"opponent": user_display(row.player_2 if is_p1 else row.player_1),
				"opponent_score": row.player_2_score if is_p1 else row.player_1_score,
				"my_bir_before": row.player_1_bir_before if is_p1 else row.player_2_bir_before,
				"my_bir_after": row.player_1_bir_after if is_p1 else row.player_2_bir_after,
				"completed_at": row.completed_at,
			}
		)
	return history


def battle_state(battle, slot: str) -> dict:
	opp_slot = opponent_slot(slot)
	return {
		"battle": battle.name,
		"status": battle.status,
		"current_question_index": battle.current_question_index,
		"total_questions": battle.total_questions,
		"remaining_ms": _remaining_ms(battle),
		"my_score": battle.get(f"{slot}_score"),
		"opponent_score": battle.get(f"{opp_slot}_score"),
		"my_ready": bool(battle.get(f"{slot}_ready")),
		"opponent_ready": bool(battle.get(f"{opp_slot}_ready")),
		"opponent": user_display(battle.get(opp_slot)),
		"winner": battle.winner,
	}


def _remaining_ms(battle):
	if battle.status != "In Progress" or not battle.question_start_time:
		return None
	elapsed_ms = int(time_diff_in_seconds(now_datetime(), battle.question_start_time) * 1000)
	return max(0, ANSWER_WINDOW_MS - elapsed_ms)


def check_and_advance(battle) -> None:
	"""Mutates `battle` in place. Called opportunistically from every
	battle-scoped whitelisted method plus the cron backstop — this is the
	ONLY place question-advancement/forfeit rules are implemented."""
	if battle.status != "In Progress":
		return

	if _is_stale(battle.player_1_last_seen) or _is_stale(battle.player_2_last_seen):
		_check_forfeit(battle)
		if battle.status != "In Progress":
			return

	deadline_passed_ms = (
		time_diff_in_seconds(now_datetime(), battle.question_start_time) * 1000
		if battle.question_start_time
		else 0
	)
	both_answered = _both_answered(battle, battle.current_question_index)

	if not (deadline_passed_ms > ANSWER_WINDOW_MS + ANSWER_GRACE_MS or both_answered):
		return

	if battle.current_question_index >= battle.total_questions:
		_finalize_battle(battle)
		return

	battle.current_question_index += 1
	battle.question_start_time = now_datetime()


def _both_answered(battle, question_index: int) -> bool:
	return frappe.db.count(
		"TOB Bible Battle Answer", {"battle": battle.name, "question_index": question_index}
	) >= 2


def _is_stale(last_seen) -> bool:
	if not last_seen:
		return False
	return time_diff_in_seconds(now_datetime(), last_seen) > FORFEIT_SECONDS


def _check_forfeit(battle) -> None:
	p1_stale = _is_stale(battle.player_1_last_seen)
	p2_stale = _is_stale(battle.player_2_last_seen)
	if p1_stale and p2_stale:
		battle.status = "Abandoned"
		battle.completed_at = now_datetime()
	elif p1_stale:
		_finalize_battle(battle, forced_winner_slot="player_2")
	elif p2_stale:
		_finalize_battle(battle, forced_winner_slot="player_1")


def _finalize_battle(battle, forced_winner_slot: str | None = None) -> None:
	battle.status = "Completed"
	battle.completed_at = now_datetime()

	if forced_winner_slot:
		winner_slot = forced_winner_slot
	elif battle.player_1_score > battle.player_2_score:
		winner_slot = "player_1"
	elif battle.player_2_score > battle.player_1_score:
		winner_slot = "player_2"
	else:
		winner_slot = None

	battle.winner = battle.get(winner_slot) if winner_slot else None
	_update_ratings(battle, winner_slot)


def _update_ratings(battle, winner_slot: str | None) -> None:
	rating_1 = get_or_create_rating(battle.player_1)
	rating_2 = get_or_create_rating(battle.player_2)

	if winner_slot == "player_1":
		outcome_1 = 1.0
	elif winner_slot == "player_2":
		outcome_1 = 0.0
	else:
		outcome_1 = 0.5

	new_bir_1, new_bir_2 = rating_module.apply_battle_result(rating_1.bir, rating_2.bir, outcome_1)

	battle.player_1_bir_before = rating_1.bir
	battle.player_1_bir_after = new_bir_1
	battle.player_2_bir_before = rating_2.bir
	battle.player_2_bir_after = new_bir_2

	_apply_rating_update(rating_1, new_bir_1, outcome_1, battle.player_1_score)
	_apply_rating_update(rating_2, new_bir_2, 1 - outcome_1, battle.player_2_score)


def _apply_rating_update(rating_doc, new_bir: int, outcome: float, points_scored: int) -> None:
	rating_doc.bir = new_bir
	rating_doc.games_played = (rating_doc.games_played or 0) + 1
	rating_doc.total_points = (rating_doc.total_points or 0) + (points_scored or 0)

	if outcome == 1.0:
		rating_doc.wins = (rating_doc.wins or 0) + 1
		rating_doc.current_streak = (rating_doc.current_streak or 0) + 1 if (rating_doc.current_streak or 0) >= 0 else 1
		rating_doc.best_streak = max(rating_doc.best_streak or 0, rating_doc.current_streak)
	elif outcome == 0.0:
		rating_doc.losses = (rating_doc.losses or 0) + 1
		rating_doc.current_streak = 0
	else:
		rating_doc.draws = (rating_doc.draws or 0) + 1
		rating_doc.current_streak = 0

	rating_doc.save(ignore_permissions=True)


def sweep_stale_battles() -> None:
	"""Cron backstop (see hooks.py's scheduler_events) — only reached when
	nobody has polled an In Progress battle recently enough for
	check_and_advance to run opportunistically (e.g. both apps died
	mid-question). Normal play never needs this."""
	names = frappe.get_all("TOB Bible Battle", filters={"status": "In Progress"}, pluck="name")
	for name in names:
		battle = frappe.get_doc("TOB Bible Battle", name)
		check_and_advance(battle)
		battle.save(ignore_permissions=True)
		frappe.db.commit()
