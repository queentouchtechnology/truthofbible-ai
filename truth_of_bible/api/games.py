"""Bible games (Complete the Verse, Guess the Character, Who Said It?, Word
Scramble, Treasure Hunt) plus the shared XP / badges / missions /
leaderboard layer that Bible Battle also feeds.

Session-cookie auth; every call acts for frappe.session.user only. The
game doctypes grant no REST permission to normal roles, so these are the
only door. `language` is 'ta' or 'en' (the app's global language);
`country` is the player's ISO country, used for the leaderboard filter.
"""

import frappe

from truth_of_bible.games.arcade import progress, session


def _user() -> str:
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Please sign in to play."), frappe.PermissionError)
	return frappe.session.user


@frappe.whitelist(methods=["GET", "POST"])
def get_hub(language: str | None = None, country: str | None = None) -> dict:
	return session.hub(_user(), language, country)


@frappe.whitelist(methods=["POST"])
def start_round(game: str, language: str | None = None, country: str | None = None) -> dict:
	return session.start_round(_user(), game, language, country)


@frappe.whitelist(methods=["POST"])
def submit_answer(session_name: str, index: int, answer: str | None = None, clues_used: int = 1, hints_used: int = 0) -> dict:
	return session.answer(_user(), session_name, index, answer, clues_used, hints_used)


@frappe.whitelist(methods=["POST"])
def finish_round(session_name: str) -> dict:
	return session.finish(_user(), session_name)


@frappe.whitelist(methods=["GET", "POST"])
def get_leaderboard(board: str = "xp", period: str = "week", country: str | None = None) -> dict:
	board = board if board in ("xp", "bir") else "xp"
	period = period if period in ("week", "month", "all") else "week"
	return progress.leaderboard(_user(), board, period, country)


@frappe.whitelist(methods=["GET", "POST"])
def get_badges(language: str | None = None) -> dict:
	"""Badge text is always English (dashboard text); `language` is ignored."""
	return {"badges": progress.badges(_user())}
