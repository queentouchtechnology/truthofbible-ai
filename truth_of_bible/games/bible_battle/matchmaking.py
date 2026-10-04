"""Server-side, poll-driven matchmaking. No background job/cron is
involved in finding a match (see the plan's rationale: this codebase has
no frappe.enqueue precedent, and a poll-driven scan-on-every-call design
is simpler and just as correct for V1 scale) — every start_matchmaking
call itself re-runs the opponent scan, so a newly-joined opponent is
picked up by the next poll from whoever is already waiting.

The scan runs on EVERY search call — start_matchmaking and each
get_match_status poll — not only when someone new joins. Otherwise two
players already waiting (both queued at the same moment, or too far apart
in BIR when the second arrived) were never paired, and the tolerance that
widens the longer a player waits (matchmaking_rules) never got a chance
to apply.

Race safety: the scan locks ALL Searching rows (the caller's own
included) in one SELECT ... ORDER BY name FOR UPDATE — a consistent lock
order, so two players polling at the same moment queue up behind each
other instead of deadlocking or both creating a battle. The second one
re-reads after the first commits and finds its own row already Matched.

Only players searching in the same question language are matched
(Tamil with Tamil, English with English).
"""

import random
import string

import frappe
from frappe import _
from frappe.utils import now_datetime, time_diff_in_seconds

from truth_of_bible.games.bible_battle.matchmaking_rules import STALE_QUEUE_SECONDS, is_compatible
from truth_of_bible.games.bible_battle.utils import get_or_create_rating

#: Excludes ambiguous characters (0/O, 1/I) so a code is easy to read aloud
#: or retype after sharing via a plain-text share sheet.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 6


def normalize_language(language: str | None) -> str:
	"""'ta' for Tamil, else 'en' — the two question banks battles use."""
	value = (language or "").strip().lower()
	return "ta" if value in ("ta", "tamil") else "en"


def _scan_and_claim(user: str, rating, language: str, now) -> str | None:
	"""Finds a compatible waiting opponent and creates the battle. Returns
	the battle name, or None. Marks both queue rows Matched. Must run
	inside the request's transaction (row locks held until commit)."""
	rows = frappe.db.sql(
		"""
		SELECT name, player, bir_snapshot, queued_at, language
		FROM `tabTOB Bible Battle Queue`
		WHERE status = 'Searching'
		ORDER BY name
		FOR UPDATE
		""",
		as_dict=True,
	)
	mine = next((r for r in rows if r.player == user), None)
	my_elapsed = time_diff_in_seconds(now, mine.queued_at) if mine else 0

	for candidate in sorted((r for r in rows if r.player != user), key=lambda r: r.queued_at):
		elapsed = time_diff_in_seconds(now, candidate.queued_at)
		if elapsed >= STALE_QUEUE_SECONDS:
			frappe.db.set_value("TOB Bible Battle Queue", candidate.name, "status", "Cancelled")
			continue
		if normalize_language(candidate.language) != language:
			continue
		if not is_compatible(rating.bir, candidate.bir_snapshot, my_elapsed, elapsed):
			continue

		battle = frappe.get_doc(
			{
				"doctype": "TOB Bible Battle",
				"player_1": candidate.player,
				"player_2": user,
				"status": "Waiting",
				"language": language,
				"waiting_since": now,
			}
		)
		battle.insert(ignore_permissions=True)
		frappe.db.set_value(
			"TOB Bible Battle Queue", candidate.name, {"status": "Matched", "matched_battle": battle.name}
		)
		if mine:
			frappe.db.set_value("TOB Bible Battle Queue", mine.name, {"status": "Matched", "matched_battle": battle.name})
		return battle.name
	return None


def start_matchmaking(user: str, language: str | None = None) -> dict:
	rating = get_or_create_rating(user)
	language = normalize_language(language)
	now = now_datetime()

	battle = _scan_and_claim(user, rating, language, now)
	if battle:
		return {"status": "matched", "battle": battle}

	if not frappe.db.exists("TOB Bible Battle Queue", {"player": user, "status": "Searching"}):
		frappe.get_doc(
			{
				"doctype": "TOB Bible Battle Queue",
				"player": user,
				"bir_snapshot": rating.bir,
				"language": language,
				"queued_at": now,
				"status": "Searching",
			}
		).insert(ignore_permissions=True)
	return {"status": "searching"}


def cancel_matchmaking(user: str) -> dict:
	rows = frappe.get_all("TOB Bible Battle Queue", filters={"player": user, "status": "Searching"}, pluck="name")
	for name in rows:
		frappe.db.set_value("TOB Bible Battle Queue", name, "status", "Cancelled")
	return {"status": "cancelled"}


def _generate_invite_code() -> str:
	for _attempt in range(20):
		code = "".join(random.choices(_CODE_ALPHABET, k=_CODE_LENGTH))
		if not frappe.db.exists("TOB Bible Battle", {"invite_code": code, "status": "Pending"}):
			return code
	frappe.throw(_("Could not generate an invite code — please try again."))


def create_challenge(user: str, language: str | None = None) -> dict:
	"""Direct challenge: bypasses BIR matchmaking entirely. player_1 is set
	immediately; player_2 stays blank until someone calls join_challenge
	with the code, at which point the battle moves from Pending to Waiting
	and the normal ready-up/battle flow takes over unchanged."""
	get_or_create_rating(user)
	code = _generate_invite_code()
	battle = frappe.get_doc(
		{
			"doctype": "TOB Bible Battle",
			"player_1": user,
			"status": "Pending",
			"invite_code": code,
			"language": normalize_language(language),
		}
	)
	battle.insert(ignore_permissions=True)
	return {"battle": battle.name, "invite_code": code}


def join_challenge(code: str, user: str) -> dict:
	code = (code or "").strip().upper()
	if not code:
		frappe.throw(_("Enter an invite code."))

	# Row lock so two people racing to use the same code can't both join it.
	locked = frappe.db.sql(
		"""
		SELECT name, player_1, status
		FROM `tabTOB Bible Battle`
		WHERE invite_code = %s AND status = 'Pending'
		ORDER BY creation DESC
		LIMIT 1
		FOR UPDATE
		""",
		(code,),
		as_dict=True,
	)
	if not locked or locked[0].status != "Pending":
		frappe.throw(_("That invite code is invalid or has already been used."))

	row = locked[0]
	if row.player_1 == user:
		frappe.throw(_("You can't join your own challenge."))

	get_or_create_rating(user)
	frappe.db.set_value(
		"TOB Bible Battle", row.name, {"player_2": user, "status": "Waiting", "waiting_since": now_datetime()}
	)
	return {"battle": row.name}


def cancel_challenge(battle_name: str, user: str) -> dict:
	battle = frappe.get_doc("TOB Bible Battle", battle_name)
	if battle.player_1 != user or battle.status != "Pending":
		frappe.throw(_("This challenge can't be cancelled."), frappe.PermissionError)
	battle.status = "Cancelled"
	battle.save(ignore_permissions=True)
	return {"status": "cancelled"}


def get_match_status(user: str) -> dict:
	row = frappe.db.get_value(
		"TOB Bible Battle Queue",
		{"player": user},
		["name", "status", "matched_battle", "queued_at", "language"],
		as_dict=True,
		order_by="creation desc",
	)
	if not row:
		return {"status": "idle"}
	if row.status == "Matched":
		return {"status": "matched", "battle": row.matched_battle}
	if row.status == "Cancelled":
		return {"status": "cancelled"}

	# Still searching: look for an opponent on every poll (see module doc).
	now = now_datetime()
	battle = _scan_and_claim(user, get_or_create_rating(user), normalize_language(row.language), now)
	if battle:
		return {"status": "matched", "battle": battle}
	return {"status": "searching", "elapsed_seconds": time_diff_in_seconds(now, row.queued_at)}
