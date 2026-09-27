"""Bible Reading Plans — age-tiered (Kids/Teens/Young Adults/Adults/Seniors/
All Ages), multi-day plans a user can browse, start, and track day-by-day.

Every doctype here (`TOB Reading Plan`, `TOB Reading Plan Day`,
`TOB User Reading Plan`) is closed to raw `/api/resource/...` REST for every
role except System Manager — including the enrolled user themselves — same
reasoning as the Bible Battle plan's permission model: this file is the only
door. Ownership/state checks happen here first, then the actual read/write
uses `ignore_permissions=True`. Session-cookie auth (default whitelisted
behavior, login required) — matches `api/bible.py`'s own convention, not the
static `erpToken` admin screens use.
"""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime


def _plan_dict(p) -> dict:
	return {
		"plan": p.name,
		"title": p.title,
		"age_group": p.age_group,
		"description": p.description or "",
		"duration_days": p.duration_days or 0,
		"difficulty": p.difficulty,
		"icon": p.icon,
		"accent_color": p.accent_color,
	}


def _day_dict(d) -> dict:
	return {
		"day_number": d.day_number,
		"title": d.title or "",
		"reference_label": d.reference_label,
		"book_id": d.book_id,
		"chapter_start": d.chapter_start,
		"chapter_end": d.chapter_end or d.chapter_start,
		"note": d.note or "",
	}


def _completed_days(enrollment) -> list:
	try:
		days = json.loads(enrollment.completed_days or "[]")
		return sorted({int(d) for d in days})
	except Exception:
		return []


def _enrollment_dict(e, day_count) -> dict:
	completed = _completed_days(e)
	return {
		"plan": e.plan,
		"status": e.status,
		"current_day": e.current_day or 1,
		"completed_days": completed,
		"progress_percent": round(len(completed) / day_count * 100) if day_count else 0,
		"started_at": e.started_at,
		"completed_at": e.completed_at,
	}


def _get_active_enrollment(user: str, plan: str):
	name = frappe.db.get_value(
		"TOB User Reading Plan", {"user": user, "plan": plan, "status": "Active"}, "name"
	)
	return frappe.get_doc("TOB User Reading Plan", name) if name else None


@frappe.whitelist(methods=["GET"])
def list_plans(age_group=None):
	filters = {"status": "Published"}
	if age_group:
		filters["age_group"] = age_group
	plans = frappe.get_all(
		"TOB Reading Plan",
		filters=filters,
		fields=[
			"name", "title", "age_group", "description", "duration_days",
			"difficulty", "icon", "accent_color", "sort_order",
		],
		order_by="sort_order asc, title asc",
		ignore_permissions=True,
	)

	enrollment_rows = frappe.get_all(
		"TOB User Reading Plan",
		filters={"user": frappe.session.user, "status": ["!=", "Abandoned"]},
		fields=["plan", "status", "current_day", "completed_days"],
		ignore_permissions=True,
	)
	enrollment_by_plan = {r.plan: r for r in enrollment_rows}

	rows = []
	for p in plans:
		row = _plan_dict(p)
		enrollment = enrollment_by_plan.get(p.name)
		if enrollment:
			completed = _completed_days(enrollment)
			row["enrollment_status"] = enrollment.status
			row["progress_percent"] = (
				round(len(completed) / p.duration_days * 100) if p.duration_days else 0
			)
		else:
			row["enrollment_status"] = None
			row["progress_percent"] = 0
		rows.append(row)
	return {"plans": rows}


@frappe.whitelist(methods=["GET"])
def get_plan(plan):
	p = frappe.get_doc("TOB Reading Plan", plan)
	if p.status != "Published" and "System Manager" not in frappe.get_roles():
		frappe.throw(_("This plan isn't available."), frappe.PermissionError)

	days = frappe.get_all(
		"TOB Reading Plan Day",
		filters={"plan": plan},
		fields=["day_number", "title", "reference_label", "book_id", "chapter_start", "chapter_end", "note"],
		order_by="day_number asc",
		ignore_permissions=True,
	)

	result = _plan_dict(p)
	result["days"] = [_day_dict(d) for d in days]

	enrollment = _get_active_enrollment(frappe.session.user, plan)
	if not enrollment:
		completed_name = frappe.db.get_value(
			"TOB User Reading Plan",
			{"user": frappe.session.user, "plan": plan, "status": "Completed"},
			"name",
			order_by="modified desc",
		)
		if completed_name:
			enrollment = frappe.get_doc("TOB User Reading Plan", completed_name)
	result["enrollment"] = _enrollment_dict(enrollment, len(days)) if enrollment else None
	return result


@frappe.whitelist(methods=["POST"])
def enroll(plan):
	if not frappe.db.exists("TOB Reading Plan", {"name": plan, "status": "Published"}):
		frappe.throw(_("This plan isn't available."), frappe.ValidationError)

	existing = _get_active_enrollment(frappe.session.user, plan)
	if existing:
		day_count = frappe.db.count("TOB Reading Plan Day", {"plan": plan})
		return _enrollment_dict(existing, day_count)

	doc = frappe.get_doc(
		{
			"doctype": "TOB User Reading Plan",
			"user": frappe.session.user,
			"plan": plan,
			"status": "Active",
			"current_day": 1,
			"started_at": now_datetime(),
			"last_activity_at": now_datetime(),
			"completed_days": "[]",
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	day_count = frappe.db.count("TOB Reading Plan Day", {"plan": plan})
	return _enrollment_dict(doc, day_count)


@frappe.whitelist(methods=["POST"])
def mark_day_complete(plan, day_number):
	day_number = int(day_number)
	enrollment = _get_active_enrollment(frappe.session.user, plan)
	if not enrollment:
		frappe.throw(_("Start this plan first."), frappe.ValidationError)
	if not frappe.db.exists("TOB Reading Plan Day", {"plan": plan, "day_number": day_number}):
		frappe.throw(_("That day doesn't exist on this plan."), frappe.ValidationError)

	completed = set(_completed_days(enrollment))
	completed.add(day_number)
	day_count = frappe.db.count("TOB Reading Plan Day", {"plan": plan})

	enrollment.completed_days = json.dumps(sorted(completed))
	enrollment.current_day = min(max(completed) + 1, day_count) if completed else 1
	enrollment.last_activity_at = now_datetime()
	if len(completed) >= day_count:
		enrollment.status = "Completed"
		enrollment.completed_at = now_datetime()
	enrollment.save(ignore_permissions=True)
	frappe.db.commit()

	return _enrollment_dict(enrollment, day_count)


@frappe.whitelist(methods=["POST"])
def unmark_day(plan, day_number):
	day_number = int(day_number)
	enrollment = _get_active_enrollment(frappe.session.user, plan)
	if not enrollment:
		frappe.throw(_("Start this plan first."), frappe.ValidationError)

	completed = set(_completed_days(enrollment))
	completed.discard(day_number)
	enrollment.completed_days = json.dumps(sorted(completed))
	enrollment.last_activity_at = now_datetime()
	enrollment.save(ignore_permissions=True)
	frappe.db.commit()

	day_count = frappe.db.count("TOB Reading Plan Day", {"plan": plan})
	return _enrollment_dict(enrollment, day_count)


@frappe.whitelist(methods=["POST"])
def leave_plan(plan):
	enrollment = _get_active_enrollment(frappe.session.user, plan)
	if not enrollment:
		return {"plan": plan, "status": "Abandoned"}
	enrollment.status = "Abandoned"
	enrollment.save(ignore_permissions=True)
	frappe.db.commit()
	return {"plan": plan, "status": "Abandoned"}


@frappe.whitelist(methods=["GET"])
def get_my_plans():
	rows = frappe.get_all(
		"TOB User Reading Plan",
		filters={"user": frappe.session.user, "status": ["!=", "Abandoned"]},
		fields=["name", "plan", "status", "current_day", "completed_days", "started_at", "completed_at"],
		order_by="modified desc",
		ignore_permissions=True,
	)
	if not rows:
		return {"plans": []}

	plan_names = [r.plan for r in rows]
	plans = frappe.get_all(
		"TOB Reading Plan",
		filters={"name": ["in", plan_names]},
		fields=["name", "title", "age_group", "duration_days", "icon", "accent_color"],
		ignore_permissions=True,
	)
	plans_by_name = {p.name: p for p in plans}

	result = []
	for r in rows:
		p = plans_by_name.get(r.plan)
		if not p:
			continue
		completed = _completed_days(r)
		result.append({
			"plan": p.name,
			"title": p.title,
			"age_group": p.age_group,
			"icon": p.icon,
			"accent_color": p.accent_color,
			"duration_days": p.duration_days or 0,
			"status": r.status,
			"current_day": r.current_day or 1,
			"progress_percent": round(len(completed) / p.duration_days * 100) if p.duration_days else 0,
		})
	return {"plans": result}
