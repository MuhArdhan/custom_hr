frappe.ui.form.on("Salary Structure Assignment", {
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
