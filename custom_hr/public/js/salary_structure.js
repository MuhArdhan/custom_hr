frappe.ui.form.off("Salary Structure", "open_salary_slip");

frappe.ui.form.on("Salary Structure", {
	berlaku_untuk(frm) {
		if (frm.doc.berlaku_untuk === "Khusus Outlet") {
			if (!frm.doc.lintas_company) frm.set_value("lintas_company", 1);
			if (frm.doc.hanya_department) frm.set_value("hanya_department", null);
		}
	},
	lintas_company(frm) {
		if (frm.doc.lintas_company && frm.doc.payment_account) {
			frm.set_value("payment_account", null);
		}
	},
	open_salary_slip(frm, employee) {
		const openWithFormat = (print_format) => {
			frappe.call({
				method: "hrms.payroll.doctype.salary_structure.salary_structure.make_salary_slip",
				args: {
					source_name: frm.doc.name,
					employee,
					as_print: 1,
					print_format,
					for_preview: 1,
				},
				callback(r) {
					if (!r.message) return;
					const new_window = window.open();
					new_window.document.write(r.message);
				},
			});
		};

		if (frm.doc.salary_slip_based_on_timesheet) {
			openWithFormat("Salary Slip based on Timesheet");
			return;
		}
		frappe.model.with_doctype("Salary Slip", () => {
			const default_pf = frappe.get_meta("Salary Slip")?.default_print_format;
			openWithFormat(default_pf || "Slip Gaji JURI");
		});
	},
});
