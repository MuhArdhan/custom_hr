// Frappe's Export dialog pre-checks only the mandatory fields and has no setting for it.
// Pre-check the columns HR normally exports from Attendance instead.
const ATTENDANCE_EXPORT_DEFAULTS = [
	"employee",
	"employee_name",
	"working_duration",
	"status",
	"leave_type",
	"attendance_date",
	"company",
	"shift",
	"in_time",
	"out_time",
	"late_entry_duration",
	"early_exit_duration",
];

// The Employee Name box is the title-field filter, which cannot be switched off in the field settings.
function hide_employee_name_filter(list_view) {
	const field = list_view.page.fields_dict.employee_name;
	if (field) $(field.wrapper).hide();
}

// The standard Attendance Date filter is a single day; swap it for a from/to range.
function use_date_range(list_view) {
	const single = list_view.page.fields_dict.attendance_date;
	if (!single || single.df.fieldtype === "DateRange") return;
	const range = list_view.page.add_field(
		{
			fieldtype: "DateRange",
			fieldname: "attendance_date",
			label: __("Attendance Date"),
			condition: "Between",
			onchange: () => list_view.filter_area.debounced_refresh_list_view(),
			is_filter: 1,
		},
		list_view.filter_area.standard_filters_wrapper
	);
	// A single date coming from a link or the URL becomes a one-day range. The list sets match_type "="
	// right before filling a standard filter, which would turn the range into an equality filter.
	const set_value = range.set_value.bind(range);
	range.set_value = (value) => {
		range.df.match_type = "Between";
		return set_value(typeof value === "string" && value ? [value, value] : value);
	};
	$(range.wrapper).insertBefore(single.wrapper);
	$(single.wrapper).remove();
}

const hrms_list_settings = frappe.listview_settings["Attendance"] || {};
frappe.listview_settings["Attendance"] = {
	...hrms_list_settings,
	onload(list_view) {
		hrms_list_settings.onload?.(list_view);
		hide_employee_name_filter(list_view);
		use_date_range(list_view);
	},
	refresh(list_view) {
		hrms_list_settings.refresh?.(list_view);
		hide_employee_name_filter(list_view);
		use_date_range(list_view);
	},
};

const original_export = frappe.ui.BulkOperations.prototype.export;
frappe.ui.BulkOperations.prototype.export = function (doctype, docnames) {
	if (doctype !== "Attendance") return original_export.call(this, doctype, docnames);

	// Same steps as the original; the dialog is only reachable once the lazy bundle has loaded.
	frappe.require("data_import_tools.bundle.js", () => {
		const exporter = new frappe.data_import.DataExporter(doctype, "Insert New Records");
		exporter.dialog.set_value("export_records", "by_filter");
		exporter.filter_group.add_filters_to_filter_group([[doctype, "name", "in", docnames, false]]);

		// The dialog re-selects the mandatory fields when it finishes showing; run after that.
		exporter.dialog.$wrapper.one("shown.bs.modal", () => {
			const columns = exporter.dialog.get_field(doctype);
			columns.selected_options = ATTENDANCE_EXPORT_DEFAULTS.filter((fieldname) =>
				columns.options.some((option) => option.value === fieldname)
			);
			columns.select_options(columns.selected_options);
			columns.df.on_change?.();
		});
	});
};
