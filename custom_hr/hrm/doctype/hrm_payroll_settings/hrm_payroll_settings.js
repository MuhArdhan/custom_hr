frappe.ui.form.on("HRM Payroll Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Setup Presensi Payroll"), () => {
			frappe.set_route("List", "HRM Attendance Payroll Settings");
		});
	},
});
