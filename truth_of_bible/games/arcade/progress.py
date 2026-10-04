"""Game progress shared by every game, Bible Battle included: XP and
levels, badges, daily missions, and the global leaderboard.

How it ties into the rest of the app:

- XP lives in its own ledger (TOB Game XP Ledger) — it ranks players and
  never buys anything, so it can be generous without touching the shop
  economy.
- Reward points: playing a game earns the existing `play_game` rewards rule
  (rewards/engine.py, capped per day), and that rule also counts as an
  active day for the existing daily streak.
- BIR stays Bible Battle's own Elo rating. Battles pay XP here too, and
  the leaderboard can rank by BIR as well as by XP.
- Badges and missions pay XP once each (dedupe keys), never points.
"""

import json
import math
import random

import frappe
from frappe.utils import add_days, getdate, now_datetime, nowdate

from truth_of_bible.games.arcade.rounds import GAMES

#: A player earns XP from at most this many rounds of each game per day;
#: more rounds are practice (still scored, 0 XP) so the leaderboard can't
#: be farmed.
DAILY_XP_ROUNDS = 10
PERFECT_BONUS = 20
MISSION_XP = 25
ALL_MISSIONS_XP = 50
BADGE_XP = 20
BATTLE_XP = {"win": 40, "draw": 25, "loss": 15}


# --- ledger ---------------------------------------------------------------


def _lock_user(user: str) -> None:
	frappe.db.sql("select name from `tabUser` where name=%s for update", user)


def award_xp(user: str, xp: int, source: str, title: str, dedupe_key: str, session: str | None = None) -> int:
	"""Grants XP once per (user, dedupe_key). Returns the XP granted."""
	if xp <= 0:
		return 0
	_lock_user(user)
	if frappe.db.exists("TOB Game XP Ledger", {"user": user, "dedupe_key": dedupe_key}):
		return 0
	frappe.get_doc({
		"doctype": "TOB Game XP Ledger", "user": user, "xp": xp, "source": source,
		"title": title, "dedupe_key": dedupe_key, "session": session,
	}).insert(ignore_permissions=True)
	profile = get_profile(user)
	profile.total_xp = (profile.total_xp or 0) + xp
	profile.save(ignore_permissions=True)
	return xp


def xp_today(user: str, sources: tuple | None = None) -> int:
	cond, args = "", [user, nowdate()]
	if sources:
		cond = " and source in %s"
		args.append(sources)
	return int(frappe.db.sql(
		f"select coalesce(sum(xp),0) from `tabTOB Game XP Ledger` where user=%s and creation >= %s{cond}", args
	)[0][0])


def xp_rounds_today(user: str, game: str) -> int:
	return frappe.db.count("TOB Game XP Ledger", {"user": user, "source": game, "creation": [">=", nowdate()]})


# --- profile --------------------------------------------------------------


def get_profile(user: str, country: str | None = None, language: str | None = None):
	if frappe.db.exists("TOB Game Profile", user):
		profile = frappe.get_doc("TOB Game Profile", user)
	else:
		profile = frappe.get_doc({"doctype": "TOB Game Profile", "user": user, "total_xp": 0})
		profile.insert(ignore_permissions=True)
	changed = False
	if country and (country or "").upper() != (profile.country or ""):
		profile.country = country.upper()
		changed = True
	if language and language != profile.language:
		profile.language = language
		changed = True
	if changed:
		profile.save(ignore_permissions=True)
	return profile


def _json(value, default):
	try:
		return json.loads(value) if value else default
	except ValueError:
		return default


def record_round(profile, game: str, correct: int, total: int, perfect: bool) -> None:
	stats = _json(profile.stats, {})
	s = stats.setdefault(game, {"played": 0, "correct": 0, "answered": 0, "best": 0})
	s["played"] += 1
	s["correct"] += correct
	s["answered"] += total
	s["best"] = max(s["best"], correct)
	profile.stats = json.dumps(stats)
	profile.games_played = (profile.games_played or 0) + 1
	if perfect:
		profile.perfect_rounds = (profile.perfect_rounds or 0) + 1
	profile.last_played = now_datetime()
	profile.save(ignore_permissions=True)


# --- levels ---------------------------------------------------------------

_TITLES = (
	(12, "Elder", "மூப்பர்"),
	(8, "Teacher", "போதகர்"),
	(5, "Scholar", "கல்விமான்"),
	(3, "Disciple", "சீஷன்"),
	(1, "Seeker", "தேடுபவர்"),
)


def _level_floor(level: int) -> int:
	"""XP needed to reach `level`: 0, 100, 300, 600, 1000, …"""
	return 50 * level * (level - 1)


def level_info(xp: int, language: str = "en") -> dict:
	level = int((1 + math.sqrt(1 + xp / 12.5)) / 2)
	while _level_floor(level + 1) <= xp:
		level += 1
	while level > 1 and _level_floor(level) > xp:
		level -= 1
	floor, ceil = _level_floor(level), _level_floor(level + 1)
	title = next((t for t in _TITLES if level >= t[0]))
	return {
		"level": level, "xp": xp, "level_xp": xp - floor, "level_span": ceil - floor,
		"next_level_xp": ceil, "title": title[2] if language == "ta" else title[1],
	}


# --- badges -----------------------------------------------------------------

BADGES = [
	{"code": "first_game", "icon": "flag", "en": "First Steps", "ta": "முதல் அடி", "desc_en": "Play your first game", "desc_ta": "முதல் விளையாட்டை விளையாடுங்கள்"},
	{"code": "verse_20", "icon": "menu_book", "en": "Verse Keeper", "ta": "வசனக் காவலர்", "desc_en": "Complete 20 verses", "desc_ta": "20 வசனங்களை நிறைவு செய்யுங்கள்"},
	{"code": "character_20", "icon": "person_search", "en": "Character Expert", "ta": "நபர் நிபுணர்", "desc_en": "Guess 20 characters", "desc_ta": "20 நபர்களைக் கண்டுபிடியுங்கள்"},
	{"code": "who_said_20", "icon": "record_voice_over", "en": "Listening Ear", "ta": "கவனிக்கும் செவி", "desc_en": "Name 20 speakers", "desc_ta": "20 பேசியவர்களைக் கண்டுபிடியுங்கள்"},
	{"code": "scramble_20", "icon": "abc", "en": "Word Wizard", "ta": "சொல் வித்தகர்", "desc_en": "Unscramble 20 words", "desc_ta": "20 சொற்களைச் சரிசெய்யுங்கள்"},
	{"code": "treasure_5", "icon": "diamond", "en": "Treasure Seeker", "ta": "புதையல் தேடுபவர்", "desc_en": "Finish 5 treasure hunts", "desc_ta": "5 புதையல் வேட்டைகளை முடியுங்கள்"},
	{"code": "explorer", "icon": "explore", "en": "Explorer", "ta": "ஆய்வாளர்", "desc_en": "Play all five games", "desc_ta": "ஐந்து விளையாட்டுகளையும் விளையாடுங்கள்"},
	{"code": "perfect_1", "icon": "star", "en": "Flawless", "ta": "குறையற்றவர்", "desc_en": "Score a perfect round", "desc_ta": "ஒரு சுற்றில் எல்லாம் சரி"},
	{"code": "perfect_10", "icon": "auto_awesome", "en": "Perfectionist", "ta": "பரிபூரணர்", "desc_en": "Score 10 perfect rounds", "desc_ta": "10 முழுமையான சுற்றுகள்"},
	{"code": "streak_7", "icon": "local_fire_department", "en": "Faithful Week", "ta": "உண்மையுள்ள வாரம்", "desc_en": "Keep a 7-day streak", "desc_ta": "7 நாள் தொடர்ச்சி"},
	{"code": "streak_30", "icon": "whatshot", "en": "Steadfast", "ta": "உறுதியானவர்", "desc_en": "Keep a 30-day streak", "desc_ta": "30 நாள் தொடர்ச்சி"},
	{"code": "xp_1000", "icon": "school", "en": "Scholar", "ta": "கல்விமான்", "desc_en": "Earn 1,000 XP", "desc_ta": "1,000 XP பெறுங்கள்"},
	{"code": "xp_5000", "icon": "workspace_premium", "en": "Sage", "ta": "ஞானி", "desc_en": "Earn 5,000 XP", "desc_ta": "5,000 XP பெறுங்கள்"},
	{"code": "battle_win_1", "icon": "sports_martial_arts", "en": "First Victory", "ta": "முதல் வெற்றி", "desc_en": "Win a Bible Battle", "desc_ta": "ஒரு வேதாகமப் போரில் வெல்லுங்கள்"},
	{"code": "battle_win_10", "icon": "emoji_events", "en": "Champion", "ta": "சாம்பியன்", "desc_en": "Win 10 Bible Battles", "desc_ta": "10 வேதாகமப் போர்களில் வெல்லுங்கள்"},
	{"code": "bir_1200", "icon": "trending_up", "en": "Rising Star", "ta": "உயரும் நட்சத்திரம்", "desc_en": "Reach 1,200 BIR", "desc_ta": "1,200 BIR அடையுங்கள்"},
]


def _badge_context(user: str, profile) -> dict:
	from truth_of_bible.rewards import engine as rewards

	stats = _json(profile.stats, {})
	rating = frappe.db.get_value("TOB Bible Battle Rating", user, ["bir", "wins"], as_dict=True) or {}
	return {
		"stats": stats,
		"played": profile.games_played or 0,
		"perfect": profile.perfect_rounds or 0,
		"xp": profile.total_xp or 0,
		"streak": rewards.streak(user),
		"wins": rating.get("wins") or 0,
		"bir": rating.get("bir") or 0,
	}


def _badge_met(code: str, c: dict) -> bool:
	s = c["stats"]
	correct = lambda g: (s.get(g) or {}).get("correct", 0)  # noqa: E731
	return {
		"first_game": c["played"] >= 1,
		"verse_20": correct("verse") >= 20,
		"character_20": correct("character") >= 20,
		"who_said_20": correct("who_said") >= 20,
		"scramble_20": correct("scramble") >= 20,
		"treasure_5": (s.get("treasure") or {}).get("played", 0) >= 5,
		"explorer": all((s.get(g) or {}).get("played", 0) for g in GAMES),
		"perfect_1": c["perfect"] >= 1,
		"perfect_10": c["perfect"] >= 10,
		"streak_7": c["streak"] >= 7,
		"streak_30": c["streak"] >= 30,
		"xp_1000": c["xp"] >= 1000,
		"xp_5000": c["xp"] >= 5000,
		"battle_win_1": c["wins"] >= 1,
		"battle_win_10": c["wins"] >= 10,
		"bir_1200": c["bir"] >= 1200,
	}.get(code, False)


def _badge_row(b: dict, language: str, earned_on: str | None) -> dict:
	return {
		"code": b["code"], "icon": b["icon"], "title": b[language] if language in b else b["en"],
		"description": b[f"desc_{language}"], "earned": bool(earned_on), "earned_on": earned_on,
	}


def check_badges(user: str, language: str = "en") -> list[dict]:
	"""Awards any newly met badges (+XP each) and returns them."""
	profile = get_profile(user)
	earned = _json(profile.badges, {})
	ctx = _badge_context(user, profile)
	new = []
	for b in BADGES:
		if b["code"] in earned or not _badge_met(b["code"], ctx):
			continue
		earned[b["code"]] = nowdate()
		new.append(b)
	if not new:
		return []
	profile.badges = json.dumps(earned)
	profile.save(ignore_permissions=True)
	for b in new:
		award_xp(user, BADGE_XP, "badge", f"Badge: {b['en']}", f"badge:{b['code']}")
	return [_badge_row(b, language, earned[b["code"]]) for b in new]


def badges(user: str, language: str = "en") -> list[dict]:
	earned = _json(get_profile(user).badges, {})
	return [_badge_row(b, language, earned.get(b["code"])) for b in BADGES]


# --- daily missions -------------------------------------------------------

MISSIONS = [
	{"code": "play_3", "target": 3, "en": "Play 3 games", "ta": "3 விளையாட்டுகள் விளையாடுங்கள்"},
	{"code": "correct_15", "target": 15, "en": "Get 15 answers right", "ta": "15 சரியான பதில்கள்"},
	{"code": "perfect_1", "target": 1, "en": "Score a perfect round", "ta": "ஒரு சுற்றில் எல்லாம் சரி"},
	{"code": "xp_150", "target": 150, "en": "Earn 150 XP from games", "ta": "விளையாட்டுகளில் 150 XP பெறுங்கள்"},
	{"code": "battle_1", "target": 1, "en": "Play a Bible Battle", "ta": "ஒரு வேதாகமப் போர் விளையாடுங்கள்"},
	{"code": "verse_1", "target": 1, "game": "verse", "en": "Finish a Complete the Verse round", "ta": "வசனத்தை நிறைவுசெய் ஒரு சுற்று முடியுங்கள்"},
	{"code": "character_1", "target": 1, "game": "character", "en": "Finish a Guess the Character round", "ta": "நபரைக் கண்டுபிடி ஒரு சுற்று முடியுங்கள்"},
	{"code": "who_said_1", "target": 1, "game": "who_said", "en": "Finish a Who Said It? round", "ta": "யார் சொன்னது? ஒரு சுற்று முடியுங்கள்"},
	{"code": "scramble_1", "target": 1, "game": "scramble", "en": "Finish a Word Scramble round", "ta": "சொல் புதிர் ஒரு சுற்று முடியுங்கள்"},
	{"code": "treasure_1", "target": 1, "game": "treasure", "en": "Finish a Treasure Hunt", "ta": "ஒரு புதையல் வேட்டையை முடியுங்கள்"},
]


def _todays_missions(user: str) -> list[dict]:
	"""Three missions a day, the same all day for a player, different
	between players and days."""
	rng = random.Random(f"{user}:{nowdate()}")
	general = [m for m in MISSIONS if "game" not in m]
	per_game = [m for m in MISSIONS if "game" in m]
	return rng.sample(general, 2) + rng.sample(per_game, 1)


def _mission_progress(user: str, m: dict) -> int:
	today = nowdate()
	done = {"user": user, "status": "Completed", "completed_at": [">=", today]}
	code = m["code"]
	if code == "play_3":
		battles = frappe.db.count("TOB Game XP Ledger", {"user": user, "source": "battle", "creation": [">=", today]})
		return frappe.db.count("TOB Game Session", done) + battles
	if code == "correct_15":
		return int(frappe.db.sql(
			"select coalesce(sum(correct),0) from `tabTOB Game Session` where user=%s and status='Completed' and completed_at >= %s",
			(user, today),
		)[0][0])
	if code == "perfect_1":
		return int(frappe.db.sql(
			"""select count(*) from `tabTOB Game Session` where user=%s and status='Completed'
			and completed_at >= %s and total > 0 and correct = total""", (user, today),
		)[0][0])
	if code == "xp_150":
		return xp_today(user, tuple(GAMES) + ("battle",))
	if code == "battle_1":
		return frappe.db.count("TOB Game XP Ledger", {"user": user, "source": "battle", "creation": [">=", today]})
	return frappe.db.count("TOB Game Session", {**done, "game": m["game"]})


def missions(user: str, language: str = "en", award: bool = True) -> dict:
	"""Today's missions with progress; completes (and pays) any that are
	now done. Returns {"missions": [...], "completed_now": [...]}"""
	rows, completed_now = [], []
	today = nowdate()
	for m in _todays_missions(user):
		progress = min(m["target"], _mission_progress(user, m))
		done = progress >= m["target"]
		key = f"mission:{today}:{m['code']}"
		if done and award and award_xp(user, MISSION_XP, "mission", f"Mission: {m['en']}", key):
			completed_now.append(m[language])
		rows.append({
			"code": m["code"], "title": m[language], "progress": progress, "target": m["target"],
			"done": done, "xp": MISSION_XP, "game": m.get("game"),
		})
	all_done = all(r["done"] for r in rows)
	if all_done and award and award_xp(user, ALL_MISSIONS_XP, "mission", "All daily missions", f"mission:{today}:all"):
		completed_now.append("all")
	return {"missions": rows, "all_done": all_done, "bonus_xp": ALL_MISSIONS_XP, "completed_now": completed_now}


# --- Bible Battle ----------------------------------------------------------


def on_battle_finished(battle) -> None:
	"""Called from bible_battle.engine._finalize_battle. Never raises into
	the battle — progress is a bonus, the battle result is what matters."""
	from truth_of_bible.rewards import engine as rewards

	for slot in ("player_1", "player_2"):
		user = battle.get(slot)
		if not user:
			continue
		try:
			if not battle.winner:
				outcome = "draw"
			else:
				outcome = "win" if battle.winner == user else "loss"
			award_xp(user, BATTLE_XP[outcome], "battle", f"Bible Battle — {outcome}", f"battle:{battle.name}", battle.name)
			rewards._award_rule(user, "play_game")
			language = get_profile(user).language or "en"
			check_badges(user, language)
			missions(user, language)
		except Exception:
			frappe.log_error(title="Bible Battle progress", message=frappe.get_traceback())


# --- leaderboard ------------------------------------------------------------


def _since(period: str):
	if period == "week":
		return add_days(getdate(nowdate()), -6)
	if period == "month":
		return add_days(getdate(nowdate()), -29)
	return None


def leaderboard(user: str, board: str = "xp", period: str = "week", country: str | None = None, limit: int = 50) -> dict:
	country = (country or "").strip().upper() or None
	args: list = []
	if board == "bir":
		cond = " and p.country = %s" if country else ""
		if country:
			args.append(country)
		rows = frappe.db.sql(
			f"""select r.user, r.bir as score, p.country
			from `tabTOB Bible Battle Rating` r left join `tabTOB Game Profile` p on p.user = r.user
			where r.games_played > 0{cond} order by r.bir desc, r.wins desc""",
			args, as_dict=True,
		)
	else:
		since = _since(period)
		if since:
			cond = " and l.creation >= %s"
			args.append(since)
		else:
			cond = ""
		if country:
			cond += " and p.country = %s"
			args.append(country)
		rows = frappe.db.sql(
			f"""select l.user, sum(l.xp) as score, p.country
			from `tabTOB Game XP Ledger` l left join `tabTOB Game Profile` p on p.user = l.user
			where 1=1{cond} group by l.user, p.country having score > 0 order by score desc""",
			args, as_dict=True,
		)
	me = None
	for i, r in enumerate(rows):
		r["rank"] = i + 1
		if r.user == user:
			me = r
	top = rows[:limit]
	names = {}
	wanted = [r.user for r in top] + ([me.user] if me else [])
	if wanted:
		for u in frappe.get_all("User", filters={"name": ["in", wanted]}, fields=["name", "full_name", "user_image"]):
			names[u.name] = u
	xp_by_user = dict(frappe.get_all("TOB Game Profile", filters={"user": ["in", wanted or [""]]}, fields=["user", "total_xp"], as_list=True))

	def row(r):
		u = names.get(r.user) or {}
		return {
			"rank": r["rank"], "user": r.user, "name": u.get("full_name") or "Player", "image": u.get("user_image"),
			"country": r.country, "score": int(r.score or 0), "level": level_info(int(xp_by_user.get(r.user) or 0))["level"],
			"is_me": r.user == user,
		}

	countries = frappe.db.sql(
		"""select country, count(*) as players from `tabTOB Game Profile`
		where country is not null and country != '' and total_xp > 0 group by country order by players desc limit 40""",
		as_dict=True,
	)
	return {
		"board": board, "period": period, "country": country,
		"rows": [row(r) for r in top], "me": row(me) if me else None, "total": len(rows),
		"countries": [{"code": c.country, "players": c.players} for c in countries],
	}
