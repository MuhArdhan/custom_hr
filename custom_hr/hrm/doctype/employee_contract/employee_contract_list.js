frappe.listview_settings["Employee Contract"] = {
	add_fields: ["start_date", "end_date", "contract_type", "docstatus"],
	has_indicator_for_draft: true,
	has_indicator_for_cancelled: true,
	onload(listview) {
		listview.page.add_inner_button(__("Akan Berakhir (30 Hari)"), () => {
			const today = frappe.datetime.get_today();
			frappe.set_route("List", "Employee Contract", {
				docstatus: 1,
				start_date: ["<=", today],
				end_date: ["between", [today, frappe.datetime.add_days(today, 30)]],
			});
		});
	},
	get_indicator(doc) {
		if (doc.docstatus === 2) return [__("Dibatalkan"), "red", "docstatus,=,2"];
		if (doc.docstatus === 0) return [__("Draft"), "gray", "docstatus,=,0"];
		const today = frappe.datetime.get_today();
		if (doc.start_date > today) return [__("Belum Berlaku"), "blue", `start_date,>,${today}|docstatus,=,1`];
		if (doc.end_date && doc.end_date < today) return [__("Berakhir"), "orange", `end_date,<,${today}|docstatus,=,1`];
		return [__("Aktif"), "green"];
	},
};
