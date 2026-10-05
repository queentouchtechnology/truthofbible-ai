frappe.ui.form.on("TOB Reading Plan", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Generate days"), () => {
			if (!frm.doc.generate_books || !frm.doc.generate_days) {
				frappe.msgprint(__("Set Books and Number of days (under 'Generate days from books') first, then save."));
				return;
			}
			frappe.confirm(
				__("Replace this plan's days with {0} days generated from books {1}?", [frm.doc.generate_days, frm.doc.generate_books]),
				() => frappe.call({
					method: "truth_of_bible.api.reading_plan.generate_days",
					args: { plan: frm.doc.name, books: frm.doc.generate_books, days: frm.doc.generate_days, replace: 1 },
					freeze: true,
					callback: (r) => {
						frappe.show_alert({ message: __("{0} days generated", [r.message.days]), indicator: "green" });
						frm.reload_doc();
					},
				})
			);
		});
	},
});
