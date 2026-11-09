const hrms_salary_slip_list = frappe.listview_settings["Salary Slip"] || {};

frappe.listview_settings["Salary Slip"] = {
	...hrms_salary_slip_list,
	onload(list_view) {
		hrms_salary_slip_list.onload?.(list_view);
		// through the Payroll Entry, unlike the list's own Submit, so the Hutang Gaji journal is booked
		if (frappe.model.can_submit("Payroll Entry")) {
			list_view.page.add_inner_button(__("Bulk Submit Salary Slip"), () => open_bulk_payroll("submit", list_view));
		}
	},
};
