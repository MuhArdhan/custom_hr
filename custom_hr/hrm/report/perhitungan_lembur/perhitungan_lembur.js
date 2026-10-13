frappe.query_reports["Perhitungan Lembur"] = {
	filters: [
		{
			fieldname: "bulan",
			label: __("Bulan"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
	],
	onload(report) {
		report.page.add_inner_button(__("Buat Additional Salary"), () => {
			const bulan = report.get_filter_value("bulan");
			frappe.confirm(
				__("Buat draft Additional Salary Lembur untuk bulan ini?"),
				() => {
					frappe
						.xcall("custom_hr.api.overtime_pay.generate_overtime_salary", {
							bulan,
						})
						.then((result) => {
							const created = result.created || [];
							const skipped = result.skipped || [];
							let msg = __("Draft dibuat: {0}", [
								created.length ? created.join(", ") : "-",
							]);
							if (skipped.length) {
								msg +=
									"<br>" +
									__("Dilewati (sudah submitted): {0}", [
										skipped.join(", "),
									]);
							}
							frappe.msgprint(msg);
							report.refresh();
						});
				}
			);
		});
	},
};
