frappe.ui.form.on("TOB Automation Keys", {
	refresh(frm) {
		frm.add_custom_button(__("Create Pickup Code"), () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the keys first."));
				return;
			}
			frappe.call({
				method: "truth_of_bible.truth_of_bible.doctype.tob_automation_keys.tob_automation_keys.new_pickup_code",
				freeze: true,
				callback: (r) => {
					frm.reload_doc();
					frappe.msgprint({
						title: __("Pickup code"),
						message: __("Send this code to Claude (works once, for 30 minutes):") + `<h3 style="user-select:all">${r.message.code}</h3>`,
					});
				},
			});
		});
	},
});
