frappe.ui.form.on("Leave Application", {
	refresh(frm) {
		frm.set_query("leave_type", () => ({
			query: "custom_hr.services.employee_scope.leave_type_query",
			filters: { employee: frm.doc.employee || "" },
		}));
	},
});
