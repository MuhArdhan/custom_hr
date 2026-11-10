const hrms_ssa_list = frappe.listview_settings["Salary Structure Assignment"] || {};

frappe.listview_settings["Salary Structure Assignment"] = {
	...hrms_ssa_list,
	onload(list_view) {
		hrms_ssa_list.onload?.(list_view);
		if (frappe.model.can_read("Bulk Salary Structure Assignment")) {
			list_view.page.add_inner_button(__("Bulk Assign"), () =>
				frappe.set_route("Form", "Bulk Salary Structure Assignment", "Bulk Salary Structure Assignment")
			);
		}
	},
};
