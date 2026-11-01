// Preview as on the site, and the Publish / Reject buttons (truth_of_bible.api.articles).
frappe.ui.form.on("TOB Article", {
	refresh(frm) {
		render_preview(frm);
		if (frm.is_new()) return;
		const api = "truth_of_bible.api.articles.";

		if (frm.doc.status === "Pending") {
			frm.add_custom_button(__("Publish"), () => {
				if (frm.is_dirty()) return frappe.msgprint(__("Save your changes first."));
				frappe.confirm(
					__("Publish <b>{0}</b> on truthofbible.org/{1}/ ?<br><br>Did you check the verse text on the cover image?",
						[frappe.utils.escape_html(frm.doc.title), frm.doc.slug]),
					() => frappe.call({ method: api + "publish", args: { name: frm.doc.name }, freeze: true,
						freeze_message: __("Publishing…") })
						.then((r) => { frm.reload_doc(); frappe.msgprint(r.message.message); })
				);
			}).addClass("btn-primary");

			frm.add_custom_button(__("Reject"), () => {
				frappe.prompt({ fieldname: "reason", fieldtype: "Small Text", label: __("Why? (optional)") },
					(v) => frappe.call({ method: api + "reject", args: { name: frm.doc.name, reason: v.reason } })
						.then(() => frm.reload_doc()),
					__("Reject this article"), __("Reject"));
			});
		}

		if (frm.doc.status === "Published") {
			frm.add_custom_button(__("Update on Site"), () => {
				if (frm.is_dirty()) return frappe.msgprint(__("Save your changes first."));
				frappe.call({ method: api + "publish", args: { name: frm.doc.name }, freeze: true, freeze_message: __("Updating…") })
					.then((r) => { frm.reload_doc(); frappe.msgprint(r.message.message); });
			});
			frm.add_custom_button(__("Open"), () => window.open(frm.doc.url, "_blank"));
		}

		if (frm.doc.status === "Rejected") {
			frm.add_custom_button(__("Back to Pending"), () =>
				frappe.call({ method: api + "reopen", args: { name: frm.doc.name } }).then(() => frm.reload_doc()));
		}
	},
	html: render_preview,
	cover_image: render_preview,
	title: render_preview,
	excerpt: render_preview,
});

function render_preview(frm) {
	const d = frm.doc, esc = frappe.utils.escape_html;
	frm.get_field("preview").$wrapper.html(`
		<div style="max-width:720px;font:16px/1.7 Georgia,serif;color:var(--text-color)">
			<h1 style="font-size:1.8em;line-height:1.25;margin:0 0 .3em">${esc(d.title || "")}</h1>
			<p style="font-style:italic;color:var(--text-muted)">${esc(d.excerpt || "")}</p>
			${d.cover_image ? `<img src="${encodeURI(d.cover_image)}" alt="" style="width:100%;border-radius:10px;margin:.5em 0">` : ""}
			<div class="tob-article-body">${d.html || ""}</div>
		</div>
		<style>.tob-article-body blockquote{border-left:4px solid #d4a017;margin:1em 0;padding:.2em 1em}
		.tob-article-body .wp-block-button__link{display:inline-block;padding:.5em 1.2em;border-radius:999px;background:#d4a017;color:#111}</style>`);
}
