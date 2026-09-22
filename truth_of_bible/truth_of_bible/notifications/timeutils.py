"""Small timezone helpers shared by the notification engine and the
spiritual/reading scan — kept in one place so "what does 'now' mean for
this user" is answered exactly once, correctly, rather than re-derived
(and possibly re-broken) in every module that needs it.
"""

from datetime import timedelta

import pytz
from frappe.utils import get_system_timezone, now_datetime


def safe_tz(name: str | None):
	try:
		return pytz.timezone(name or "Asia/Kolkata")
	except Exception:
		return pytz.timezone("Asia/Kolkata")


def local_now(user_timezone: str | None):
	"""`now_datetime()` is naive, in the SITE's own configured timezone
	(System Settings), not necessarily the bench server OS's timezone and
	not UTC — so it's localized against `get_system_timezone()` explicitly
	rather than relying on naive-datetime.astimezone()'s "assume system
	local time" behavior, which would silently use the wrong zone if the
	bench process's OS timezone differs from the site's configured one.
	"""
	site_tz = pytz.timezone(get_system_timezone())
	site_aware = site_tz.localize(now_datetime())
	return site_aware.astimezone(safe_tz(user_timezone))


def time_to_seconds(value) -> float:
	"""Frappe `Time` fields come back as `datetime.timedelta` from the ORM;
	tolerate a plain "HH:MM:SS" string too (e.g. a default that hasn't been
	round-tripped through the ORM yet)."""
	if isinstance(value, timedelta):
		return value.total_seconds()
	if not value:
		return 0.0
	parts = str(value).split(":")
	h, m, s = (parts + ["0", "0", "0"])[:3]
	return int(h) * 3600 + int(m) * 60 + float(s or 0)


def in_quiet_hours(now_local, start_value, end_value) -> bool:
	"""Handles a quiet-hours window that wraps past midnight (e.g. 21:00 ->
	07:00) as well as one that doesn't."""
	start = time_to_seconds(start_value)
	end = time_to_seconds(end_value)
	now_seconds = now_local.hour * 3600 + now_local.minute * 60 + now_local.second
	if start == end:
		return False
	if start < end:
		return start <= now_seconds < end
	return now_seconds >= start or now_seconds < end
