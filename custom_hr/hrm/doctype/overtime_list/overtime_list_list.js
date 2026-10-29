frappe.listview_settings["Overtime List"] = {
	onload(listview) {
		// Looks like the single-date standard filter, but takes one date or a range.
		const range = listview.page.add_field({
			fieldname: "date",
			fieldtype: "DateRange",
			label: __("Tanggal Lembur"),
			condition: "Between",
			change: () => listview.filter_area.refresh_list_view(),
		});
		const parse_range = range.parse.bind(range);
		range.parse = (value) => one_date_or_range(parse_range, value);
		// keep the place the standard filter had: after Company, before Jenis Lembur
		const company = listview.page.fields_dict.company;
		if (company) range.$wrapper.insertAfter(company.$wrapper);
	},
};

// A single picked date (the picker closed after one click) filters that day only.
function one_date_or_range(parse_range, value) {
	const parsed = parse_range(value);
	if (parsed || !value || typeof value === "object") return parsed;
	const day = moment(frappe.datetime.user_to_obj(value)).format("YYYY-MM-DD");
	return day === "Invalid date" ? undefined : [day, day];
}
