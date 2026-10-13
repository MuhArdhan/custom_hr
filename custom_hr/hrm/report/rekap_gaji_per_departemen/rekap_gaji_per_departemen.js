frappe.query_reports["Rekap Gaji per Departemen"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("Dari Tanggal"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_start(),
		},
		{
			fieldname: "to_date",
			label: __("Sampai Tanggal"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_end(),
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: "PT. JUARA ROTI INDONESIA",
		},
	],
};
