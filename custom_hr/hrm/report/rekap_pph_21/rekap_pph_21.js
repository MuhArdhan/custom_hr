frappe.query_reports["Rekap PPh 21"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("Dari Tanggal"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("Sampai Tanggal"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
			reqd: 1,
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
		},
		{
			fieldname: "payroll_entry",
			label: __("Payroll Entry"),
			fieldtype: "Link",
			options: "Payroll Entry",
		},
		{
			fieldname: "include_draft",
			label: __("Tampilkan Slip Draft"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "simulasi_ter",
			label: __("Simulasi Tarif TER (Meski Toggle Nonaktif)"),
			fieldtype: "Check",
			default: 0,
		},
	],
};
