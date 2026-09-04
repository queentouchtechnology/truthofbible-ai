"""Small shared helpers used by matchmaking.py/engine.py — kept here rather
than duplicated in both, per the "single source of truth" reasoning in the
plan (only games/bible_battle needs these; nothing app-wide yet, so this is
NOT a games/common/ package)."""

import json
import random

import frappe
from frappe import _
from frappe.utils import now_datetime

from truth_of_bible.games.bible_battle.rating import STARTING_BIR

QUESTION_DISTRIBUTION = {"Easy": 3, "Medium": 5, "Hard": 2}


def get_or_create_rating(user: str):
	"""autoname=user on TOB Bible Battle Rating makes this a plain get-or-insert."""
	if frappe.db.exists("TOB Bible Battle Rating", user):
		return frappe.get_doc("TOB Bible Battle Rating", user)
	rating = frappe.get_doc(
		{"doctype": "TOB Bible Battle Rating", "user": user, "bir": STARTING_BIR}
	)
	rating.insert(ignore_permissions=True)
	return rating


def require_participant(battle, user: str) -> str:
	"""Returns 'player_1' or 'player_2' if `user` is a participant in
	`battle`, else raises PermissionError. The one ownership check every
	battle-scoped API method must call before touching game state."""
	if user == battle.player_1:
		return "player_1"
	if user == battle.player_2:
		return "player_2"
	frappe.throw(_("You are not a participant in this battle."), frappe.PermissionError)


def opponent_slot(slot: str) -> str:
	return "player_2" if slot == "player_1" else "player_1"


def user_display(user: str | None) -> dict | None:
	"""Battle/Answer/Queue docs only ever store a bare User name (email) —
	this resolves the bit of profile the client actually needs to render an
	opponent (name + avatar), without exposing the full User document."""
	if not user:
		return None
	info = frappe.db.get_value("User", user, ["full_name", "user_image"], as_dict=True)
	if not info:
		return {"user": user, "name": user, "image": None}
	return {"user": user, "name": info.full_name or user, "image": info.user_image}


def touch_last_seen(battle, slot: str) -> None:
	battle.set(f"{slot}_last_seen", now_datetime())


def select_question_sequence(language: str = "en") -> list[str]:
	"""Picks 3 Easy + 5 Medium + 2 Hard published questions, randomized
	within and across difficulty, returned as an ordered list of question
	names. Raises if the bank doesn't have enough seeded questions yet."""
	sequence: list[str] = []
	for difficulty, count in QUESTION_DISTRIBUTION.items():
		pool = frappe.get_all(
			"TOB Bible Battle Question",
			filters={"status": "Published", "difficulty": difficulty, "language": language},
			pluck="name",
		)
		if len(pool) < count:
			frappe.throw(
				_("Not enough published {0} questions to start a battle ({1} available, {2} needed).").format(
					difficulty, len(pool), count
				)
			)
		sequence.extend(random.sample(pool, count))
	random.shuffle(sequence)
	return sequence


def encode_question_sequence(sequence: list[str]) -> str:
	return json.dumps(sequence)


def decode_question_sequence(raw: str | None) -> list[str]:
	return json.loads(raw) if raw else []
