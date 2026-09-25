import frappe
import requests

from frappe import _
from frappe.utils.file_manager import save_file


def _token_is_for_this_app(access_token) -> bool:
	"""Strict: a Google access token is accepted only if it was issued to one
	of OUR OAuth clients (`google_client_ids` in site_config). Anything else —
	another app's token, an unreadable audience, an empty or missing list —
	is refused. The audience seen is written to Error Log (once per value) so
	the right client IDs can be copied into site_config."""
	try:
		r = requests.get(
			"https://oauth2.googleapis.com/tokeninfo", params={"access_token": access_token}, timeout=15
		)
		if r.status_code != 200:
			return False
		info = r.json()
	except Exception:
		frappe.log_error(title="Google login audience check failed", message=frappe.get_traceback())
		return False
	audiences = {a for a in (info.get("aud"), info.get("azp")) if a}
	allowed = {str(c) for c in (frappe.get_site_config().get("google_client_ids") or [])}
	ok = bool(audiences & allowed)
	if not ok:
		seen = ",".join(sorted(audiences)) or "(none)"
		if not frappe.cache().get_value(f"google_aud_refused:{seen}"):
			frappe.cache().set_value(f"google_aud_refused:{seen}", 1)
			frappe.log_error(
				title="Google login refused: audience not allowed",
				message=f"Audience seen: {seen}. If this is your app, add it to google_client_ids in site_config.json.",
			)
	return ok


@frappe.whitelist(allow_guest=True)
def google_login(access_token, referralCode=None):
	# `referralCode` is accepted only so older app builds that still send it
	# don't break the call — it is no longer acted on here. New-account
	# referrals now go through truth_of_bible.rewards.api.claim_referral,
	# called by the app after a successful signup.
	try:
		# ===============================
		# VERIFY GOOGLE TOKEN
		# ===============================

		google_api = "https://www.googleapis.com/oauth2/v3/userinfo"
		headers = {"Authorization": f"Bearer {access_token}"}
		res = requests.get(google_api, headers=headers, timeout=15)

		if res.status_code != 200:
			return {"status": "error", "message": "Invalid Google token"}

		data = res.json()
		if not _token_is_for_this_app(access_token):
			return {"status": "error", "message": "Invalid Google token"}

		email = data.get("email")
		if data.get("email_verified") in (False, "false", "False", 0):
			return {"status": "error", "message": "Google email is not verified"}
		full_name = data.get("name")
		picture = data.get("picture")

		if not email:
			return {"status": "error", "message": "Email not found"}

		if not full_name:
			full_name = email.split("@")[0]

		# ===============================
		# CREATE USER
		# ===============================

		if not frappe.db.exists("User", email):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": full_name,
					"enabled": 1,
					"user_type": "Website User",
					"send_welcome_email": 0,
				}
			)
			user.insert(ignore_permissions=True)

			for role in ["Customer", "Blogger", "LMS Student"]:
				user.append("roles", {"role": role})

			user.save(ignore_permissions=True)

		# ===============================
		# SAVE PROFILE IMAGE
		# only if null/google url
		# ===============================

		if picture:
			try:
				user_doc = frappe.get_doc("User", email)
				existing_image = user_doc.user_image or ""
				needs_update = (
					not existing_image
					or "googleusercontent.com" in existing_image
					or existing_image.startswith("https://lh3.googleusercontent.com")
				)

				if needs_update:
					image_response = requests.get(picture, timeout=20)
					if image_response.status_code == 200:
						file_doc = save_file(
							fname=f"{email}_profile.jpg",
							content=image_response.content,
							dt="User",
							dn=email,
							is_private=0,
						)
						user_doc.user_image = file_doc.file_url
						user_doc.save(ignore_permissions=True)
			except Exception:
				frappe.log_error(frappe.get_traceback(), "Profile Image Error")

		frappe.local.login_manager.login_as(email)

		profile_image = frappe.db.get_value("User", email, "user_image")

		response = {
			"status": "success",
			"message": _("Logged In"),
			"home_page": "/app/overview",
			"full_name": frappe.get_value("User", email, "full_name"),
			"user_id": email,
			"profile_image": frappe.utils.get_url() + profile_image if profile_image else "",
		}

		frappe.db.commit()
		return response

	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "Google Login Error")
		return {"status": "error", "message": str(e)}
