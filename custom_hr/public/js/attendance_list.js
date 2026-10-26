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
