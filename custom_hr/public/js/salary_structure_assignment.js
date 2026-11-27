frappe.ui.form.on("Salary Structure Assignment", {
	setup(frm) {
		frm.set_query("salary_structure", () => ({
			query: "custom_hr.services.salary_structure_scope.salary_structure_query",
			filters: {
				company: frm.doc.company,
				employee: frm.doc.employee,
			},
		}));
	},
	company(frm) {
		if (!frm.doc.company || frm.doc.payroll_payable_account) return;
		frappe.call({
			method: "custom_hr.services.payroll_payable.get_default_payable_account",
			args: { company: frm.doc.company },
			callback(r) {
				if (r.message && !frm.doc.payroll_payable_account) {
					frm.set_value("payroll_payable_account", r.message);
				}
			},
		});
	},
});
