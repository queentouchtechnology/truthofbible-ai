"""Communication Center — reusable Audience Groups: a named, admin-curated
list of users, so an admin doesn't have to re-pick the same set of people
campaign after campaign. Deliberately a flat JSON member list (the same
convention `TOB Communication Campaign` already uses for its own
`audience_user_ids`), not a child table — groups are hand-curated and
bounded, not a bulk-import mechanism.

Group membership is resolved once, at campaign-creation time, via
`audience.resolve_audience("GROUP", audience_ref=group_id)` — the same
snapshot-once semantics every other audience type in this app already has
(see campaign.py's `create_campaign`). Deleting or editing a group later
never touches campaigns already created from it.

Every whitelisted method here starts with `auth.require_admin()` —
Decision 12, never trust client-side UI visibility as the real boundary.
"""

import json

import frappe
from frappe import _

from truth_of_bible.communication.auth import require_admin


def _parse_ids(value) -> list[str]:
	if isinstance(value, str):
		try:
			return json.loads(value) if value else []
		except Exception:
			return []
	return list(value or [])


def _valid_user_ids(user_ids: list) -> list[str]:
	ids = [u for u in (user_ids or []) if u]
	if not ids:
		return []
	rows = frappe.get_all(
		"User",
		filters={"name": ["in", ids], "user_type": "Website User", "enabled": 1},
		pluck="name",
	)
	valid = set(rows)
	# Preserve the caller's ordering rather than whatever `in` returns.
	return list(dict.fromkeys(u for u in ids if u in valid))


def _member_rows(user_ids: list) -> list[dict]:
	if not user_ids:
		return []
	rows = frappe.get_all(
		"User",
		filters={"name": ["in", user_ids]},
		fields=["name", "full_name"],
	)
	by_email = {r.name: r.full_name for r in rows}
	return [
		{"email": uid, "full_name": by_email.get(uid) or uid}
		for uid in user_ids
		if uid in by_email
	]


def _group_summary(doc) -> dict:
	ids = _parse_ids(doc.member_user_ids)
	return {
		"group_id": doc.name,
		"group_name": doc.group_name,
		"members": _member_rows(ids),
		"member_count": len(ids),
	}


@frappe.whitelist(methods=["GET"])
def list_groups():
	require_admin()
	groups = frappe.get_all(
		"TOB Communication Group",
		fields=["name", "group_name", "member_user_ids", "modified"],
		order_by="modified desc",
	)
	return [
		{
			"group_id": g.name,
			"group_name": g.group_name,
			"member_count": len(_parse_ids(g.member_user_ids)),
			"updated_at": g.modified,
		}
		for g in groups
	]


@frappe.whitelist(methods=["GET"])
def get_group(group_id):
	require_admin()
	doc = frappe.get_doc("TOB Communication Group", group_id)
	return _group_summary(doc)


@frappe.whitelist(methods=["POST"])
def create_group(group_name, member_user_ids=None):
	require_admin()
	group_name = (group_name or "").strip()
	if not group_name:
		frappe.throw(_("Give this group a name."), frappe.ValidationError)

	ids = _valid_user_ids(_parse_ids(member_user_ids))
	doc = frappe.get_doc({
		"doctype": "TOB Communication Group",
		"group_name": group_name,
		"member_user_ids": json.dumps(ids),
	})
	doc.insert(ignore_permissions=True)
	return _group_summary(doc)


@frappe.whitelist(methods=["POST"])
def rename_group(group_id, group_name):
	require_admin()
	group_name = (group_name or "").strip()
	if not group_name:
		frappe.throw(_("Give this group a name."), frappe.ValidationError)

	doc = frappe.get_doc("TOB Communication Group", group_id)
	doc.group_name = group_name
	doc.save(ignore_permissions=True)
	return _group_summary(doc)


@frappe.whitelist(methods=["POST"])
def add_members(group_id, member_user_ids):
	require_admin()
	doc = frappe.get_doc("TOB Communication Group", group_id)
	existing = _parse_ids(doc.member_user_ids)
	incoming = _valid_user_ids(_parse_ids(member_user_ids))
	doc.member_user_ids = json.dumps(list(dict.fromkeys(existing + incoming)))
	doc.save(ignore_permissions=True)
	return _group_summary(doc)


@frappe.whitelist(methods=["POST"])
def remove_member(group_id, user_id):
	require_admin()
	doc = frappe.get_doc("TOB Communication Group", group_id)
	existing = _parse_ids(doc.member_user_ids)
	doc.member_user_ids = json.dumps([u for u in existing if u != user_id])
	doc.save(ignore_permissions=True)
	return _group_summary(doc)


@frappe.whitelist(methods=["POST"])
def delete_group(group_id):
	require_admin()
	frappe.delete_doc("TOB Communication Group", group_id, ignore_permissions=True)
	return {"deleted": True}
