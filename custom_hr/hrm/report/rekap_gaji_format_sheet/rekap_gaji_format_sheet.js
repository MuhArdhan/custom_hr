frappe.query_reports["Rekap Gaji Format Sheet"] = {
	filters: [
		{
			fieldname: "payroll_entry",
			label: __("Payroll Entry"),
			fieldtype: "Link",
			options: "Payroll Entry",
			reqd: 1,
		},
	],
};
