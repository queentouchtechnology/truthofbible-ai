frappe.ui.form.on("TOB Error Tracking Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Send Test Error"), () => {
			frappe.call({
				method: "truth_of_bible.errors.send_test",
				freeze: true,
				callback: (r) => frappe.msgprint(r.message),
			});
		});
	},
});
