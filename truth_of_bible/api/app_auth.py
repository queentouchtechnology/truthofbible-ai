"""Mobile-app authentication — per-user API credentials.

The app used to ship the Administrator API key and do everything (signup,
password reset, every read) as Administrator. These methods replace that:

- Every signed-in user gets THEIR OWN API key/secret (created on first use,
  returned at login), so Frappe enforces that user's own roles and
  permissions on every request — the same model `community_sso` already uses
  for Discourse.
- The steps that genuinely need elevated rights before login (signup, OTP,
  password reset) happen here, server-side, with fixed roles, rate limits
  and the OTP checked in the same request that changes the password.

Nothing here ever returns an OTP or another user's data.
"""

import secrets

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import add_to_date, cint, get_datetime, now_datetime, validate_email_address
from frappe.utils.password import get_decrypted_password, set_encrypted_password, update_password

# Roles every self-registered app member gets (was chosen by the app itself;
# same as Google sign-up). Not Blogger (a desk role) and not Customer (the
# ERPNext portal role — nothing in the app or backend checks it).
APP_MEMBER_ROLES = ("LMS Student",)

_OTP_TTL_MINUTES = 5
# Content lives in Frappe (Email Template doctype, seeded by
# install.seed_otp_email_template) so it's editable from the desk without a
# code change. The strings below are only the fallback used if that record
# is ever deleted.
_OTP_EMAIL_TEMPLATE = "OTP Verification Email"
_OTP_MAX_ATTEMPTS = 5
_OTP_COOLDOWN_SECONDS = 30
_RESET_TOKEN_TTL_SECONDS = 600
_CHANNELS = ("email", "whatsapp")


# ---------------------------------------------------------------- credentials


def _credentials(user: str) -> dict:
	"""This user's own API key/secret, created on first use. Reuses an
	existing pair so signing in on a second device doesn't sign out the
	first (rotating the secret would)."""
	if user in ("Guest", "Administrator"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not frappe.db.get_value("User", user, "enabled"):
		frappe.throw(_("This account is disabled"), frappe.AuthenticationError)

	api_key = frappe.db.get_value("User", user, "api_key")
	api_secret = (
		get_decrypted_password("User", user, "api_secret", raise_exception=False) if api_key else None
	)
	if not api_key or not api_secret:
		api_key = api_key or frappe.generate_hash(length=15)
		api_secret = frappe.generate_hash(length=15)
		set_encrypted_password("User", user, api_secret, "api_secret")
		# The column must hold the masked placeholder (as Frappe's own
		# generate_keys leaves it): an EMPTY Password field makes the next
		# save of this User (profile edit, role change, ...) delete the
		# stored secret, which silently breaks the member's key.
		frappe.db.set_value(
			"User", user, {"api_key": api_key, "api_secret": "*" * len(api_secret)}, update_modified=False
		)
	return {"api_key": api_key, "api_secret": api_secret, "auth": f"token {api_key}:{api_secret}"}


def _profile(user: str) -> dict:
	"""Same fields the app's LoginResponse already parses."""
	roles = frappe.get_roles(user)
	return {
		"status": "success",
		"message": _("Logged In"),
		"home_page": "/app/overview",
		"full_name": frappe.db.get_value("User", user, "full_name"),
		"user_id": user,
		"roles": roles,
		"accountType": "Admin" if "System Manager" in roles else "User",
	}


def signed_in_payload(user: str) -> dict:
	"""Profile + this user's own credentials — what every login returns."""
	return {**_profile(user), **_credentials(user)}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=300)
def login(usr: str, pwd: str) -> dict:
	"""Email/mobile + password. Also starts a normal session (cookies), so
	older code paths that still send the session cookie keep working."""
	login_manager = frappe.auth.LoginManager()
	try:
		login_manager.authenticate(usr, pwd)
		login_manager.post_login()
	except frappe.AuthenticationError:
		frappe.clear_messages()
		return {"status": "error", "message": _("Invalid username or password")}
	return signed_in_payload(frappe.session.user)


@frappe.whitelist(methods=["POST"])
def get_credentials() -> dict:
	"""For a user who is already signed in (session cookie from an older app
	build): hand out their own key so the app can stop using the session."""
	return signed_in_payload(frappe.session.user)


# --------------------------------------------------------------------- signup


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=3600)
def signup(email: str, first_name: str, last_name: str = "", mobile_no: str = "") -> dict:
	"""Self-registration. Roles are fixed here — the client can't choose them."""
	email = (email or "").strip().lower()
	first_name = (first_name or "").strip()
	if not email or not validate_email_address(email):
		frappe.throw(_("Enter a valid email address"))
	if not first_name:
		frappe.throw(_("First name is required"))
	if frappe.db.exists("User", email):
		frappe.throw(_("An account with this email already exists"))

	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": first_name[:140],
			"last_name": (last_name or "").strip()[:140],
			"mobile_no": (mobile_no or "").strip()[:20],
			"user_type": "Website User",
			"enabled": 1,
			"send_welcome_email": 1,
			"roles": [{"role": r} for r in APP_MEMBER_ROLES],
		}
	)
	user.insert(ignore_permissions=True)
	return {"data": {"name": user.name, "email": user.email, "full_name": user.full_name}}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=3600)
def request_coordinator(
	email: str, first_name: str, last_name: str = "", mobile_no: str = "", company_name: str = "", company_abbr: str = ""
) -> dict:
	"""'Sign up as coordinator': a normal member account now, plus a pending
	TOB Coordinator Request. The coordinator roles are granted only when a
	System Manager approves it (see that doctype) — never from the app."""
	result = signup(email, first_name, last_name, mobile_no)
	frappe.get_doc(
		{
			"doctype": "TOB Coordinator Request",
			"user": result["data"]["name"],
			"full_name": result["data"]["full_name"],
			"mobile_no": (mobile_no or "").strip()[:20],
			"company_name": (company_name or "").strip()[:140],
			"company_abbr": (company_abbr or "").strip()[:10],
			"status": "Pending",
		}
	).insert(ignore_permissions=True)
	return {**result, "status": "pending_approval"}


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=30, seconds=300)
def user_exists(identifier: str) -> dict:
	"""True/false only — never the user record."""
	identifier = (identifier or "").strip()
	exists = bool(identifier) and bool(
		frappe.db.exists("User", identifier.lower()) or frappe.db.exists("User", {"mobile_no": identifier})
	)
	return {"exists": exists}


# ------------------------------------------------------------------------ OTP


def _normalize_contact(contact: str, channel: str) -> str:
	contact = (contact or "").strip()
	return contact.lower() if channel == "email" else contact


def _send(contact: str, channel: str, otp: str) -> None:
	if channel == "email":
		subject = _("Your verification code")
		message = _("Your code is <b>{0}</b>. It is valid for {1} minutes.").format(otp, _OTP_TTL_MINUTES)
		try:
			template = frappe.get_cached_doc("Email Template", _OTP_EMAIL_TEMPLATE)
			context = {"otp": otp, "minutes": _OTP_TTL_MINUTES}
			subject = frappe.render_template(template.subject, context) or subject
			message = frappe.render_template(template.response, context) or message
		except frappe.DoesNotExistError:
			pass
		frappe.sendmail(recipients=[contact], subject=subject, message=message, now=True)
		return

	# WhatsApp goes through Chatwoot (credentials already in site_config.json —
	# see communication/chatwoot.py), with the approved OTP template the old
	# `send_otps` Server Script used.
	from truth_of_bible.communication import chatwoot

	conf = frappe.conf
	conversation_id, error = chatwoot.find_or_create_conversation(contact, contact)
	ok = False
	if conversation_id:
		ok, _message_id, error = chatwoot.send_template_message(
			conversation_id,
			conf.get("whatsapp_otp_template") or "reference_number",
			conf.get("whatsapp_otp_template_category") or "UTILITY",
			conf.get("whatsapp_otp_template_language") or "en",
			[otp],
		)
	if not ok:
		frappe.log_error(title="App auth: WhatsApp OTP not sent", message=str(error))
		frappe.throw(_("Couldn't send the WhatsApp code right now. Please try again."))


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=600)
def send_otp(contact: str, channel: str = "email", purpose: str = "login") -> dict:
	"""Before login: email codes to an existing account only (password
	reset). After login: a user may verify a phone for their own profile.
	The code is never part of the response."""
	channel = (channel or "email").lower()
	if channel not in _CHANNELS:
		frappe.throw(_("Invalid channel"))
	contact = _normalize_contact(contact, channel)
	if not contact:
		frappe.throw(_("Contact is required"))
	purpose = purpose or "login"
	masked = (contact[:2] + "****") if len(contact) >= 4 else "****"
	sent = {"status": "success", "message": _("Code sent to {0}").format(masked), "expiry_in_seconds": _OTP_TTL_MINUTES * 60}

	if frappe.session.user == "Guest":
		if channel != "email":
			frappe.throw(_("Please sign in to verify a phone number"), frappe.PermissionError)
		if not frappe.db.exists("User", contact):
			# Same answer as success — don't reveal which emails have accounts.
			return sent

	if frappe.db.exists(
		"OTP Verification",
		{"contact": contact, "creation": [">", add_to_date(now_datetime(), seconds=-_OTP_COOLDOWN_SECONDS)]},
	):
		frappe.throw(_("Please wait a moment before requesting another code"))

	for name in frappe.get_all(
		"OTP Verification",
		filters={"contact": contact, "channel": channel, "purpose": purpose, "is_used": 0},
		pluck="name",
	):
		frappe.delete_doc("OTP Verification", name, ignore_permissions=True)

	otp = f"{secrets.randbelow(10000):04d}"
	frappe.get_doc(
		{
			"doctype": "OTP Verification",
			"contact": contact,
			"channel": channel,
			"purpose": purpose,
			"otp": otp,
			"expiry": add_to_date(now_datetime(), minutes=_OTP_TTL_MINUTES),
			"is_used": 0,
			"attempts": 0,
		}
	).insert(ignore_permissions=True)
	_send(contact, channel, otp)
	return sent


def _check_otp(contact: str, channel: str, purpose: str, otp: str) -> None:
	"""Raises unless `otp` is the current code; consumes it on success."""
	rows = frappe.get_all(
		"OTP Verification",
		filters={"contact": contact, "channel": channel, "purpose": purpose, "is_used": 0},
		fields=["name", "otp", "expiry", "attempts"],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		frappe.throw(_("Code not found or already used. Please request a new one."))
	row = rows[0]
	if now_datetime() > get_datetime(row.expiry):
		frappe.db.set_value("OTP Verification", row.name, "is_used", 1)
		frappe.db.commit()
		frappe.throw(_("This code has expired. Please request a new one."))
	attempts = row.attempts or 0
	if attempts >= _OTP_MAX_ATTEMPTS:
		frappe.db.set_value("OTP Verification", row.name, "is_used", 1)
		frappe.db.commit()
		frappe.throw(_("Too many attempts. Please request a new code."))
	if not secrets.compare_digest(str(row.otp).strip(), str(otp or "").strip()):
		attempts += 1
		frappe.db.set_value(
			"OTP Verification", row.name, {"attempts": attempts, "is_used": int(attempts >= _OTP_MAX_ATTEMPTS)}
		)
		frappe.db.commit()  # keep the attempt count even though we throw
		left = _OTP_MAX_ATTEMPTS - attempts
		frappe.throw(
			_("Invalid code. {0} attempts left.").format(left) if left > 0 else _("Too many attempts. Please request a new code.")
		)
	frappe.db.set_value("OTP Verification", row.name, "is_used", 1)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=600)
def verify_otp(contact: str, otp: str, channel: str = "email", purpose: str = "login") -> dict:
	"""Before login (email): returns a short-lived `reset_token` for
	`reset_password`. Signed in: confirms the code (phone verification)."""
	channel = (channel or "email").lower()
	contact = _normalize_contact(contact, channel)
	purpose = purpose or "login"
	_check_otp(contact, channel, purpose, otp)

	result = {"status": "success", "message": _("Code verified")}
	if frappe.session.user == "Guest" and channel == "email" and frappe.db.exists("User", contact):
		token = secrets.token_urlsafe(32)
		frappe.cache().set_value(f"tob_pw_reset:{token}", contact, expires_in_sec=_RESET_TOKEN_TTL_SECONDS)
		result["reset_token"] = token
	return result


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=600)
def reset_password(reset_token: str, new_password: str) -> dict:
	"""Set a new password using the token from `verify_otp` (single use)."""
	key = f"tob_pw_reset:{reset_token or ''}"
	user = frappe.cache().get_value(key)
	if not reset_token or not user:
		frappe.throw(_("This reset link has expired. Please verify your email again."))
	frappe.cache().delete_value(key)
	if not new_password or len(new_password) < 8:
		frappe.throw(_("Password must be at least 8 characters"))
	update_password(user, new_password)
	return {"status": "success", "message": _("Password updated")}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=600)
def change_password(new_password: str) -> dict:
	"""The signed-in user changes their OWN password (profile screen)."""
	user = frappe.session.user
	if user in ("Guest", "Administrator"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not new_password or len(new_password) < 8:
		frappe.throw(_("Password must be at least 8 characters"))
	update_password(user, new_password)
	return {"status": "success", "message": _("Password updated")}


# ----------------------------------------------------------------- update


def _version_tuple(v: str) -> tuple:
	nums = []
	for p in (v or "").strip().split("."):
		try:
			nums.append(int(p))
		except ValueError:
			nums.append(0)
	return tuple((nums + [0, 0, 0])[:3])


@frappe.whitelist(allow_guest=True)
def check_app_update(current_version: str = "") -> dict:
	"""Same answer as the old `check_app_update` Server Script, but open to
	guests too — a signed-out app must still be told to update (the forced
	update is what lets the old shared admin key be rotated)."""
	s = frappe.get_cached_doc("App Settings")
	playstore_url = s.playstore_url or ""
	if s.maintenance_mode:
		return {"maintenance_mode": 1, "message": _("App is under maintenance. Please try again later."),
			"playstore_url": playstore_url}
	latest = (s.latest_version or "1.0.0").strip()
	required = int(bool(current_version) and _version_tuple(current_version) < _version_tuple(latest))
	return {"maintenance_mode": 0, "latest_version": latest, "force_update": s.force_update or 0,
		"update_required": required, "message": s.message or _("New update available"), "playstore_url": playstore_url}


# --------------------------------------------------------------- profile

# Fields a member may change on their own User record from the app.
_PROFILE_FIELDS = (
	"first_name", "last_name", "gender", "mobile_no", "user_image", "cover_image", "birth_date",
	"location", "city", "country", "language", "education",
)
# What another member may see.
_PUBLIC_FIELDS = ("name", "full_name", "first_name", "last_name", "user_image", "cover_image")
_HIDDEN = {"api_key", "api_secret", "reset_password_key", "last_reset_password_key_generated_on", "new_password",
	"login_before", "login_after", "restrict_ip", "last_ip", "last_known_versions"}


def _is_user_admin() -> bool:
	return bool(set(frappe.get_roles()) & {"System Manager"})


@frappe.whitelist()
def get_profile(user: str | None = None) -> dict:
	"""Your own User record (same shape as /api/resource/User/<id>), or the
	public fields of another member."""
	me = frappe.session.user
	if me == "Guest":
		frappe.throw(_("Please sign in"), frappe.PermissionError)
	user = (user or me).strip()
	if not frappe.db.exists("User", user):
		frappe.throw(_("User not found"), frappe.DoesNotExistError)
	doc = frappe.get_doc("User", user).as_dict()
	if user != me and not _is_user_admin():
		return {"data": {k: doc.get(k) for k in _PUBLIC_FIELDS}}
	return {"data": {k: v for k, v in doc.items() if k not in _HIDDEN}}


@frappe.whitelist(methods=["POST", "PUT"])
def update_profile(data=None, **kwargs) -> dict:
	"""Update the signed-in member's own profile (whitelisted fields only)."""
	me = frappe.session.user
	if me in ("Guest", "Administrator"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	data = frappe.parse_json(data) if isinstance(data, str) else (data or {})
	data = {**{k: v for k, v in kwargs.items() if k != "cmd"}, **data}
	changes = {k: v for k, v in data.items() if k in _PROFILE_FIELDS}
	if not changes:
		frappe.throw(_("Nothing to update"))
	doc = frappe.get_doc("User", me)
	if "education" in changes and not doc.meta.has_field("education"):
		changes.pop("education")
	doc.update({k: v for k, v in changes.items() if doc.meta.has_field(k)})
	doc.save(ignore_permissions=True)
	return {"data": {k: v for k, v in doc.as_dict().items() if k not in _HIDDEN}}


@frappe.whitelist()
@rate_limit(limit=60, seconds=60)
def find_members(query: str = "") -> list:
	"""Send-money recipient search: name + email of up to 20 enabled members
	matching `query` (min 2 characters). Never the full member list."""
	me = frappe.session.user
	if me == "Guest":
		frappe.throw(_("Please sign in"), frappe.PermissionError)
	query = (query or "").strip()
	if len(query) < 2:
		return []
	like = f"%{query}%"
	rows = frappe.get_all(
		"User",
		filters={"enabled": 1, "name": ["not in", ["Administrator", "Guest", me]]},
		or_filters={"full_name": ["like", like], "name": ["like", like]},
		fields=["name", "full_name"],
		limit_page_length=20,
		order_by="full_name asc",
	)
	return [{"name": r.full_name or r.name, "email": r.name, "role": ""} for r in rows]


# ------------------------------------------------------------- push devices


@frappe.whitelist(methods=["POST"])
def save_fcm_token(fcm_token: str = "", device: str = "android", remove: int = 0) -> str:
	"""Register this phone's push token for the signed-in member.

	One row per token (not per member + device type), so a member's phones
	and tablets all get notifications, and a token belongs only to whoever
	is signed in on that phone now — it moves when someone else signs in
	there. `remove=1` (sent on sign-out) deletes just this phone's row.
	The sender prunes tokens Google reports as dead, so old devices clear
	themselves.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	fcm_token = (fcm_token or "").strip()
	if not fcm_token:
		# Older app versions sign out with an empty token: nothing identifies
		# the phone, so leave it — it moves on the next sign-in there.
		return "ignored"
	# Real FCM tokens are long and space-free. Refuse placeholders such as
	# "Token Not Found": saving one used to replace the phone's real token,
	# which the sender then pruned, leaving it with no pushes at all.
	if len(fcm_token) < 64 or " " in fcm_token:
		frappe.throw(_("Invalid push token"), frappe.ValidationError)
	if cint(remove):
		frappe.db.delete("User FCM Token", {"user": user, "fcm_token": fcm_token})
		return "removed"
	# This phone now belongs to this member only.
	frappe.db.delete("User FCM Token", {"fcm_token": fcm_token, "user": ["!=", user]})
	name = frappe.db.get_value("User FCM Token", {"user": user, "fcm_token": fcm_token})
	if name:
		frappe.db.set_value("User FCM Token", name, "device", device)
	else:
		frappe.get_doc({"doctype": "User FCM Token", "user": user, "fcm_token": fcm_token, "device": device}).insert(
			ignore_permissions=True
		)
	return "success"
