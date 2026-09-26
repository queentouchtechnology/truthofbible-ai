"""One-time cleanup patch (2026-09-26): merges `TOB WhatsApp Conversation`
rows that share the same phone number into one, reassigning their
`TOB WhatsApp Message` rows onto the kept conversation and deleting the
duplicates.

Root cause (already fixed separately — see `communication/chatwoot.py`'s
`find_or_create_conversation` and `communication/campaign.py`'s
`_send_whatsapp`): a bug that created a brand-new Chatwoot conversation on
every campaign send instead of reusing an existing one, so the same phone
number could accumulate several conversation rows here.

**Scope**: this patch only touches this site's LOCAL mirror
(TOB WhatsApp Conversation/Message) — it never calls Chatwoot's API and
never changes anything on the Chatwoot side. A customer's own conversation
history inside Chatwoot itself is untouched; only the admin app's
duplicate list rows are cleaned up here.

Kept conversation per phone number, in priority order:
1. The row with `user` set (a real linked account) — if more than one
   qualifies, the one with the latest `last_message_at`.
2. Otherwise, the row with the latest `last_message_at`.

The kept row's `last_message_at`/`last_message_preview` are taken from
whichever merged row actually has the latest `last_message_at` (real data,
not re-derived), and `unread_count` is the sum across all merged rows.
`status` prefers OPEN > PENDING > RESOLVED, so a merged thread that's
still open anywhere doesn't get hidden as resolved.

Safe to re-run: after the first run, every phone number maps to exactly
one conversation, so a second run finds nothing left to merge.
"""

import frappe

_STATUS_PRIORITY = {"OPEN": 0, "PENDING": 1, "RESOLVED": 2}


def execute():
	rows = frappe.get_all(
		"TOB WhatsApp Conversation",
		fields=["name", "phone", "user", "status", "last_message_at", "last_message_preview", "unread_count"],
		filters={"phone": ["not in", ("", None)]},
	)

	by_phone = {}
	for r in rows:
		by_phone.setdefault(r.phone, []).append(r)

	merged_count = 0
	for convos in by_phone.values():
		if len(convos) < 2:
			continue

		convos.sort(key=lambda c: (1 if c.user else 0, c.last_message_at or ""), reverse=True)
		keep, duplicates = convos[0], convos[1:]

		total_unread = sum((c.unread_count or 0) for c in convos)
		latest = max(convos, key=lambda c: c.last_message_at or "")
		statuses = [c.status or "OPEN" for c in convos]
		best_status = min(statuses, key=lambda s: _STATUS_PRIORITY.get(s, 0))

		for dup in duplicates:
			frappe.db.set_value(
				"TOB WhatsApp Message", {"conversation": dup.name}, "conversation", keep.name
			)
			frappe.delete_doc(
				"TOB WhatsApp Conversation", dup.name, ignore_permissions=True, force=True, delete_permanently=True
			)
			merged_count += 1

		frappe.db.set_value(
			"TOB WhatsApp Conversation",
			keep.name,
			{
				"last_message_at": latest.last_message_at,
				"last_message_preview": latest.last_message_preview,
				"unread_count": total_unread,
				"status": best_status,
			},
		)

	frappe.db.commit()
	print(f"[merge_duplicate_whatsapp_conversations] Merged {merged_count} duplicate conversation(s).")
