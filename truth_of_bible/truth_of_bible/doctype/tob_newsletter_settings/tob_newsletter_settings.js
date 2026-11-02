frappe.ui.form.on("TOB Newsletter Settings", {
	refresh(frm) {
		const call = (method, args, done) =>
			frappe.call({ method: `truth_of_bible.communication.newsletter.${method}`, args, freeze: true }).then((r) => done(r.message));

		frm.add_custom_button(__("Send Test to Me"), () =>
			call("send_test", {}, (m) => frappe.show_alert({ message: __("Issue {0} sent to {1}", [m.issue_no, m.sent_to]), indicator: "green" }))
		);
		frm.add_custom_button(__("Send Next Issue Now"), () =>
			frappe.confirm(__("Send the next issue to every user now?"), () =>
				call("send_next_now", {}, (m) => {
					frappe.show_alert({ message: __("Issue {0} queued: {1}", [m.issue_no, m.campaign_id]), indicator: "green" });
					frm.reload_doc();
				})
			)
		);
		frm.add_custom_button(__("Issues"), () => frappe.set_route("List", "TOB Newsletter Issue"));
	},
});
