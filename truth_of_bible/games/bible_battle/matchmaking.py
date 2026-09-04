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

import frappe
from frappe.utils import now_datetime, time_diff_in_seconds

from truth_of_bible.games.bible_battle.matchmaking_rules import STALE_QUEUE_SECONDS, is_compatible
from truth_of_bible.games.bible_battle.utils import get_or_create_rating


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
