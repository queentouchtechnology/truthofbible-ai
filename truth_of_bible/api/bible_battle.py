"""Bible Battle's whitelisted API surface — the ONLY door into game state.
Session-cookie auth (matches bible.py's qa/qa_followup — game actions are
inherently per-player, not admin config), every function passing
frappe.session.user down into games/bible_battle/*.py so ownership is
always checked against the real authenticated caller, never a client-
supplied player id.

The underlying doctypes grant no REST permission to any non-System-Manager
role (see their .json `permissions`), so these thin wrappers are not just
convention — they are the only path by which a normal user can ever touch
Bible Battle data at all.
"""

import frappe

from truth_of_bible.games.bible_battle import engine, matchmaking
from truth_of_bible.games.bible_battle.utils import get_or_create_rating


@frappe.whitelist(methods=["POST"])
def start_matchmaking() -> dict:
	return matchmaking.start_matchmaking(frappe.session.user)


@frappe.whitelist(methods=["POST"])
def cancel_matchmaking() -> dict:
	return matchmaking.cancel_matchmaking(frappe.session.user)


@frappe.whitelist(methods=["GET", "POST"])
def get_match_status() -> dict:
	return matchmaking.get_match_status(frappe.session.user)


@frappe.whitelist(methods=["POST"])
def set_ready(battle: str) -> dict:
	return engine.set_ready(battle, frappe.session.user)


@frappe.whitelist(methods=["GET", "POST"])
def get_current_question(battle: str) -> dict:
	return engine.get_current_question(battle, frappe.session.user)


@frappe.whitelist(methods=["POST"])
def submit_answer(battle: str, question: str, selected_option: str | None = None) -> dict:
	return engine.submit_answer(battle, question, selected_option or None, frappe.session.user)


@frappe.whitelist(methods=["GET", "POST"])
def get_battle_status(battle: str) -> dict:
	return engine.get_battle_status(battle, frappe.session.user)


@frappe.whitelist(methods=["GET", "POST"])
def get_battle_result(battle: str) -> dict:
	return engine.get_battle_result(battle, frappe.session.user)


@frappe.whitelist(methods=["GET", "POST"])
def get_battle_history(limit: int = 20) -> list:
	return engine.get_battle_history(frappe.session.user, int(limit))


@frappe.whitelist(methods=["GET", "POST"])
def get_my_rating() -> dict:
	rating = get_or_create_rating(frappe.session.user)
	return {
		"bir": rating.bir,
		"games_played": rating.games_played,
		"wins": rating.wins,
		"losses": rating.losses,
		"draws": rating.draws,
		"current_streak": rating.current_streak,
		"best_streak": rating.best_streak,
		"total_points": rating.total_points,
	}
