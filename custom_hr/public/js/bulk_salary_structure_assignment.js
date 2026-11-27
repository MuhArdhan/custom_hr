frappe.ui.form.on("Bulk Salary Structure Assignment", {
	setup(frm) {
		frm.trigger("set_custom_structure_query");
	},
	refresh(frm) {
		frm.trigger("set_custom_structure_query");
	},
	set_custom_structure_query(frm) {
		frm.set_query("salary_structure", () => ({
			query: "custom_hr.services.salary_structure_scope.salary_structure_query",
			filters: {
				company: frm.doc.company,
				department: frm.doc.department,
			},
		}));
	},
	company(frm) {
		if (!frm.doc.company) return;
		frappe.db.get_value("Company", frm.doc.company, "default_payroll_payable_account", (r) => {
			if (r?.default_payroll_payable_account) {
				frm.set_value("payroll_payable_account", r.default_payroll_payable_account);
				return;
			}
			frappe.call({
				method: "custom_hr.services.payroll_payable.get_default_payable_account",
				args: { company: frm.doc.company },
				callback(res) {
					if (res.message) {
						frm.set_value("payroll_payable_account", res.message);
					}
				},
			});
		});
	},
});
