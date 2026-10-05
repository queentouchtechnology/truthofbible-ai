"""A solo game round: start → answer each item → finish.

The session row holds the answer key and the per-answer timestamps, so
correctness and the speed bonus are decided here, never by the app."""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime, time_diff_in_seconds

from truth_of_bible.games.arcade import progress, rounds
from truth_of_bible.games.bible_battle.matchmaking import normalize_language


def _load(name: str, user: str):
	session = frappe.get_doc("TOB Game Session", name, for_update=True)
	if session.user != user:
		frappe.throw(_("This is not your game."), frappe.PermissionError)
	return session


def start_round(user: str, game: str, language: str | None, country: str | None) -> dict:
	if game not in rounds.GAMES:
		frappe.throw(_("Unknown game."))
	language = normalize_language(language)
	progress.get_profile(user, country, language)
	# A round left open (app closed) is abandoned — it earns nothing.
	frappe.db.sql(
		"update `tabTOB Game Session` set status='Abandoned' where user=%s and game=%s and status='Active'",
		(user, game),
	)
	items, meta = rounds.build(game, language)
	session = frappe.get_doc({
		"doctype": "TOB Game Session", "user": user, "game": game, "language": language,
		"country": (country or "").upper() or None, "status": "Active", "started_at": now_datetime(),
		"total": len(items), "items": json.dumps({"items": items, "meta": meta}, ensure_ascii=False),
		"answers": "[]",
	})
	session.insert(ignore_permissions=True)
	return {
		"session": session.name, "game": game, "language": language, "meta": meta,
		"items": [rounds.public_item(i) for i in items],
		"xp_eligible": progress.xp_rounds_today(user, game) < progress.DAILY_XP_ROUNDS,
	}


def answer(user: str, session_name: str, index: int, given: str | None, clues_used: int = 1, hints_used: int = 0) -> dict:
	session = _load(session_name, user)
	if session.status != "Active":
		frappe.throw(_("This round has ended."))
	data = json.loads(session.items)
	answers = json.loads(session.answers or "[]")
	index = int(index)
	if index != len(answers) or index >= len(data["items"]):
		frappe.throw(_("That question was already answered."))
	now = now_datetime()
	last = answers[-1]["at"] if answers else str(session.started_at)
	seconds = time_diff_in_seconds(now, last)
	item = data["items"][index]
	correct, points = rounds.check(session.game, item, given, seconds, int(clues_used or 1), int(hints_used or 0))
	answers.append({"i": index, "given": given, "correct": correct, "points": points, "at": str(now)})
	session.answers = json.dumps(answers, ensure_ascii=False)
	session.correct = sum(1 for a in answers if a["correct"])
	session.score = sum(a["points"] for a in answers)
	session.save(ignore_permissions=True)
	return {
		"index": index, "correct": correct, "points": points, "score": session.score,
		"correct_count": session.correct, "done": len(answers) >= len(data["items"]),
		**rounds.reveal(item),
	}


def finish(user: str, session_name: str) -> dict:
	from truth_of_bible.rewards import engine as rewards

	session = _load(session_name, user)
	if session.status == "Completed":
		frappe.throw(_("This round is already finished."))
	if session.status != "Active":
		frappe.throw(_("This round has ended."))
	answered = len(json.loads(session.answers or "[]"))
	perfect = answered == session.total and session.correct == session.total and session.total > 0

	xp_before = progress.get_profile(user).total_xp or 0
	level_before = progress.level_info(xp_before)["level"]

	session.status = "Completed"
	session.completed_at = now_datetime()
	eligible = progress.xp_rounds_today(user, session.game) < progress.DAILY_XP_ROUNDS
	round_xp = (session.score + (progress.PERFECT_BONUS if perfect else 0)) if eligible and answered else 0
	session.xp_awarded = round_xp
	session.save(ignore_permissions=True)

	progress.record_round(progress.get_profile(user), session.game, session.correct, answered, perfect)
	if round_xp:
		progress.award_xp(user, round_xp, session.game, f"{session.game} round", f"round:{session.name}", session.name)
	points = rewards._award_rule(user, "play_game") if answered else 0

	# Badges, missions and levels are dashboard text: always English. Only
	# the questions themselves follow the language setting.
	new_badges = progress.check_badges(user)
	mission_state = progress.missions(user)
	xp_after = progress.get_profile(user).total_xp or 0
	level = progress.level_info(xp_after)

	meta = json.loads(session.items).get("meta") or {}
	chest = None
	if session.game == "treasure":
		chest = "gold" if session.correct >= 5 else "silver" if session.correct >= 3 else "bronze"
	return {
		"game": session.game, "correct": session.correct, "total": session.total, "score": session.score,
		"perfect": perfect, "perfect_bonus": progress.PERFECT_BONUS if perfect and eligible else 0,
		"xp_round": round_xp, "xp_total_gained": xp_after - xp_before, "xp_eligible": eligible,
		"level": level, "level_up": level["level"] > level_before,
		"reward_points": points, "streak": rewards.streak(user),
		"new_badges": new_badges, "missions": mission_state, "chest": chest, "meta": meta,
	}


def hub(user: str, language: str | None, country: str | None) -> dict:
	from truth_of_bible.rewards import engine as rewards

	language = normalize_language(language)
	profile = progress.get_profile(user, country, language)
	stats = progress._json(profile.stats, {})
	rating = frappe.db.get_value("TOB Bible Battle Rating", user, ["bir", "wins", "losses", "games_played"], as_dict=True) or {}
	all_badges = progress.badges(user)
	games = []
	for g in rounds.GAMES:
		s = stats.get(g) or {}
		games.append({
			"key": g, "played": s.get("played", 0), "best": s.get("best", 0), "size": rounds.ROUND_SIZE[g],
			"xp_rounds_left": max(0, progress.DAILY_XP_ROUNDS - progress.xp_rounds_today(user, g)),
		})
	rank = progress.leaderboard(user, "xp", "week", None, limit=0)["me"]
	return {
		"language": language,
		"country": profile.country,
		"level": progress.level_info(profile.total_xp or 0),
		"xp_today": progress.xp_today(user),
		"games_played": profile.games_played or 0,
		"streak": rewards.streak(user),
		"reward_points": rewards.balance(user),
		"bir": rating.get("bir") or 1000,
		"battle": {"wins": rating.get("wins") or 0, "losses": rating.get("losses") or 0, "played": rating.get("games_played") or 0},
		"weekly_rank": rank["rank"] if rank else None,
		"games": games,
		"missions": progress.missions(user),
		"badges": {"earned": sum(1 for b in all_badges if b["earned"]), "total": len(all_badges),
			"recent": [b for b in all_badges if b["earned"]][-3:]},
	}
