"""Articles for truthofbible.org (TOB Article), approved in the Frappe desk.

The n8n article autopilot calls submit_draft (as a System Manager API user): the article waits as Pending.
Publish commits content/articles/<slug>.json (+ the cover image) to the website repository in one commit;
the push runs the site's GitHub Actions deploy, which also sends the new URL to the indexing helper.
The repository, branch and token are in TOB Website Settings → Articles."""

import base64
import io
import json
from zoneinfo import ZoneInfo

import frappe
import requests
from frappe import _
from PIL import Image, ImageOps
from frappe.utils import get_system_timezone, now_datetime

SITE = "https://truthofbible.org"
_GH = "https://api.github.com/repos/"


@frappe.whitelist(methods=["POST"])
def submit_draft(
	title: str,
	slug: str,
	excerpt: str,
	html: str,
	kind: str = "",
	image_b64: str = "",
	image_alt: str = "",
	questions: str = "",
	image_prompt: str = "",
) -> dict:
	"""A new article from the autopilot. A slug already in use (here or live on the site) gets the date added."""
	frappe.only_for("System Manager")
	slug = slug.strip().lower()
	if frappe.db.exists("TOB Article", {"slug": slug}) or _live(slug):
		slug = f"{slug}-{now_datetime():%Y-%m-%d}"
	# a JSON list from n8n, or one question per line
	questions = json.loads(questions) if questions.strip().startswith("[") else questions.splitlines()
	doc = frappe.get_doc(
		{
			"doctype": "TOB Article",
			"title": title.strip()[:140],
			"slug": slug,
			"excerpt": excerpt.strip(),
			"html": html,
			"kind": kind,
			"image_alt": image_alt[:240],
			"image_prompt": image_prompt.strip(),
			"questions": "\n".join(q.strip() for q in questions if q.strip()),
		}
	).insert()
	if image_b64:
		f = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{slug}.png",
				"attached_to_doctype": "TOB Article",
				"attached_to_name": doc.name,
				"attached_to_field": "cover_image",
				"is_private": 1,
				"content": base64.b64decode(image_b64),
			}
		).insert()
		doc.db_set("cover_image", f.file_url)
	review = frappe.utils.get_url(f"/app/tob-article/{doc.name}")
	frappe.enqueue(_email_review, name=doc.name, review=review, enqueue_after_commit=True)
	return {"name": doc.name, "slug": doc.slug, "review": review}


def _email_review(name: str, review: str) -> None:
	"""Review link to TOB Website Settings → Review Emails (unset on a site migrated before the field existed → the admin)."""
	emails = frappe.db.get_single_value("TOB Website Settings", "articles_review_email")
	if emails is None:
		emails = "truthofbible22@gmail.com"
	recipients = [e.strip() for e in emails.replace(",", "\n").splitlines() if e.strip()]
	if not recipients:
		return
	doc = frappe.get_doc("TOB Article", name)
	frappe.sendmail(
		recipients=recipients,
		subject=f"New article to review: {doc.title}",
		message=f"<p>A new article is waiting for your approval:</p><h3>{frappe.utils.escape_html(doc.title)}</h3>"
		f"<p><i>{frappe.utils.escape_html(doc.excerpt)}</i></p>"
		f'<p><a href="{review}">Open it in the desk</a> — read it, check the verse text on the cover image, then tap '
		f"<b>Publish</b> or <b>Reject</b>.</p>",
		reference_doctype="TOB Article",
		reference_name=name,
	)


@frappe.whitelist(methods=["POST"])
def publish(name: str) -> dict:
	"""Commit the article to the website repository. Also used to update an article that is already live."""
	frappe.only_for("System Manager")
	doc = frappe.get_doc("TOB Article", name)
	if doc.status == "Rejected":
		frappe.throw(_("This article was rejected — move it back to Pending first."))
	first = doc.status != "Published"
	if first and _live(doc.slug):
		frappe.throw(_("truthofbible.org/{0}/ already exists. Change the slug and save, then publish.").format(doc.slug))

	s = frappe.get_single("TOB Website Settings")
	token = s.get_password("github_token", raise_exception=False)
	if not (s.articles_repo and token):
		frappe.throw(_("Set the GitHub repository and token in TOB Website Settings → Articles."))

	when = doc.published_on or now_datetime()
	files = {}
	image = None
	if doc.cover_image:
		image = doc.slug + ".jpg"
		files[image] = _cover(frappe.get_doc("File", {"file_url": doc.cover_image}).get_content())
	files[doc.slug + ".json"] = (json.dumps(article_json(doc, when, image), ensure_ascii=False, indent=2) + "\n").encode()
	_commit(s.articles_repo, s.articles_branch or "master", token, files,
	        ("Publish article: " if first else "Update article: ") + doc.title)

	doc.db_set({"status": "Published", "url": f"{SITE}/{doc.slug}/", "published_on": when,
	            **({"published_by": frappe.session.user} if first else {})})
	if first:
		frappe.enqueue(_open_discussion, name=doc.name, enqueue_after_commit=True)
	return {"url": doc.url, "message": _("Committed. truthofbible.org rebuilds in about 5–10 minutes: {0}").format(doc.url)}


@frappe.whitelist(methods=["POST"])
def reject(name: str, reason: str = "") -> None:
	frappe.only_for("System Manager")
	doc = frappe.get_doc("TOB Article", name)
	if doc.status != "Pending":
		frappe.throw(_("Only a pending article can be rejected."))
	doc.db_set({"status": "Rejected", "rejection_reason": (reason or "").strip()})


@frappe.whitelist(methods=["POST"])
def reopen(name: str) -> None:
	frappe.only_for("System Manager")
	doc = frappe.get_doc("TOB Article", name)
	if doc.status == "Rejected":
		doc.db_set({"status": "Pending", "rejection_reason": ""})


def article_json(doc, when, image: str | None) -> dict:
	"""The file the site reads (truthofbible-site/content/articles/README.md). Times carry the site's zone."""
	tz = ZoneInfo(get_system_timezone())
	a = {
		"title": doc.title,
		"date": when.replace(tzinfo=tz).isoformat(timespec="seconds"),
		"modified": now_datetime().replace(tzinfo=tz).isoformat(timespec="seconds"),
		"excerpt": doc.excerpt,
		"html": doc.html,
		"category": {"slug": "bible-study", "name": "Bible Study"},
	}
	if image:
		a.update(image=image, imageAlt=doc.image_alt or doc.title)
	if doc.seo_description:
		a["seoDescription"] = doc.seo_description
	return a


def _cover(content: bytes) -> bytes:
	"""Covers go into git: a 1600px-wide JPEG (~200 KB) instead of a 2 MB PNG. The site makes its own WebP sizes from it."""
	img = Image.open(io.BytesIO(content))
	img = ImageOps.exif_transpose(img).convert("RGB")
	img.thumbnail((1600, 1600))
	out = io.BytesIO()
	img.save(out, "JPEG", quality=85, optimize=True, progressive=True)
	return out.getvalue()


def _live(slug: str) -> bool:
	try:
		return requests.head(f"{SITE}/{slug}/", timeout=15, allow_redirects=False).status_code == 200
	except requests.RequestException:
		return False


def _commit(repo: str, branch: str, token: str, files: dict[str, bytes], message: str) -> None:
	"""All files in one commit (one deploy), through the Git Data API."""

	def gh(method, path, body=None):
		r = requests.request(method, _GH + repo + path, json=body, timeout=60, headers={
			"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
		if r.status_code >= 400:
			frappe.throw(_("GitHub said {0}: {1}").format(r.status_code, r.text[:300]))
		return r.json()

	head = gh("GET", f"/git/ref/heads/{branch}")["object"]["sha"]
	tree = gh("GET", f"/git/commits/{head}")["tree"]["sha"]
	entries = [
		{"path": f"content/articles/{path}", "mode": "100644", "type": "blob",
		 "sha": gh("POST", "/git/blobs", {"content": base64.b64encode(data).decode(), "encoding": "base64"})["sha"]}
		for path, data in files.items()
	]
	new_tree = gh("POST", "/git/trees", {"base_tree": tree, "tree": entries})["sha"]
	commit = gh("POST", "/git/commits", {"message": message, "tree": new_tree, "parents": [head]})["sha"]
	gh("PATCH", f"/git/refs/heads/{branch}", {"sha": commit})


def _open_discussion(name: str) -> None:
	"""Community discussion for a newly published article (n8n /webhook/tob-community-discussion), if set up."""
	s = frappe.get_single("TOB Website Settings")
	if not s.community_webhook_url:
		return
	doc = frappe.get_doc("TOB Article", name)
	headers = {}
	if s.community_webhook_header:
		headers[s.community_webhook_header] = s.get_password("community_webhook_secret", raise_exception=False) or ""
	try:
		requests.post(s.community_webhook_url, timeout=30, headers=headers, json={
			"title": doc.title, "link": doc.url, "questions": [q for q in (doc.questions or "").splitlines() if q.strip()]})
	except requests.RequestException:
		frappe.log_error(title="TOB Article: community discussion failed")
