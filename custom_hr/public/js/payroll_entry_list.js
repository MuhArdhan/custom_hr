const hrms_payroll_entry_list = frappe.listview_settings["Payroll Entry"] || {};

frappe.listview_settings["Payroll Entry"] = {
	...hrms_payroll_entry_list,
	onload(list_view) {
		hrms_payroll_entry_list.onload?.(list_view);
		if (frappe.model.can_submit("Payroll Entry")) {
			list_view.page.add_inner_button(__("Bulk Create Payroll Entry"), () => open_bulk_payroll("create", list_view));
		}
	},
};
