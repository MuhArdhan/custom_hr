frappe.query_reports["Laporan Lembur"] = {
	filters: [
		{
			fieldname: "outlet",
			label: __("Outlet"),
			fieldtype: "Link",
			options: "Outlet",
		},
		{
			fieldname: "from_date",
			label: __("Dari Tanggal"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("Sampai Tanggal"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options:
				"\nMenunggu Leader\nMenunggu SPV\nMenunggu HRD\nDisetujui\nDitolak",
		},
	],
};
