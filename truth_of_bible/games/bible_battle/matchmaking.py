"""Server-side, poll-driven matchmaking. No background job/cron is
involved in finding a match (see the plan's rationale: this codebase has
no frappe.enqueue precedent, and a poll-driven scan-on-every-call design
is simpler and just as correct for V1 scale) — every start_matchmaking
call itself re-runs the opponent scan, so a newly-joined opponent is
picked up by the next poll from whoever is already waiting.

Race safety: the opponent scan + claim happens inside one SELECT ... FOR
UPDATE, so two players calling start_matchmaking at (almost) the same
moment cannot both claim the same waiting opponent — the second
transaction blocks on the row lock until the first commits, then re-reads
and sees the row already Matched.
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


def start_matchmaking(user: str) -> dict:
	rating = get_or_create_rating(user)

	existing = frappe.db.get_value(
		"TOB Bible Battle Queue", {"player": user, "status": "Searching"}, "name"
	)
	if existing:
		return {"status": "searching", "queue": existing}

	candidates = frappe.db.sql(
		"""
		SELECT name, player, bir_snapshot, queued_at
		FROM `tabTOB Bible Battle Queue`
		WHERE status = 'Searching' AND player != %s
		ORDER BY queued_at ASC
		FOR UPDATE
		""",
		(user,),
		as_dict=True,
	)

	now = now_datetime()
	match = None
	for candidate in candidates:
		elapsed = time_diff_in_seconds(now, candidate.queued_at)
		if elapsed >= STALE_QUEUE_SECONDS:
			frappe.db.set_value("TOB Bible Battle Queue", candidate.name, "status", "Cancelled")
			continue

		if is_compatible(rating.bir, candidate.bir_snapshot, 0, elapsed):
			match = candidate
			break

	if not match:
		frappe.get_doc(
			{
				"doctype": "TOB Bible Battle Queue",
				"player": user,
				"bir_snapshot": rating.bir,
				"queued_at": now,
				"status": "Searching",
			}
		).insert(ignore_permissions=True)
		return {"status": "searching"}

	battle = frappe.get_doc(
		{
			"doctype": "TOB Bible Battle",
			"player_1": match.player,
			"player_2": user,
			"status": "Waiting",
		}
	)
	battle.insert(ignore_permissions=True)

	frappe.db.set_value("TOB Bible Battle Queue", match.name, {"status": "Matched", "matched_battle": battle.name})

	return {"status": "matched", "battle": battle.name}


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


def create_challenge(user: str) -> dict:
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
		WHERE invite_code = %s
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
	frappe.db.set_value("TOB Bible Battle", row.name, {"player_2": user, "status": "Waiting"})
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
		["name", "status", "matched_battle", "queued_at"],
		as_dict=True,
		order_by="creation desc",
	)
	if not row:
		return {"status": "idle"}
	if row.status == "Matched":
		return {"status": "matched", "battle": row.matched_battle}
	if row.status == "Cancelled":
		return {"status": "cancelled"}
	return {"status": "searching", "elapsed_seconds": time_diff_in_seconds(now_datetime(), row.queued_at)}
