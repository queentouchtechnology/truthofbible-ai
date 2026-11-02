frappe.ui.form.on("TOB Newsletter Settings", {
	refresh(frm) {
		const call = (method, args, done) =>
			frappe.call({ method: `truth_of_bible.communication.newsletter.${method}`, args, freeze: true }).then((r) => done(r.message));

		frm.add_custom_button(__("Send Test"), () =>
			frappe.prompt(
				{
					fieldname: "to",
					fieldtype: "Data",
					options: "Email",
					label: __("Send to"),
					default: frappe.session.user_email,
					description: __("Your own address, or a mail-tester.com address to see the spam score."),
					reqd: 1,
				},
				(v) => call("send_test", { to: v.to }, (m) => frappe.show_alert({ message: __("Issue {0} sent to {1}", [m.issue_no, m.sent_to]), indicator: "green" })),
				__("Send a Test Email"),
				__("Send")
			)
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
