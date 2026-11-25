frappe.ui.form.on("Shift Request", {
	refresh(frm) {
		frm.set_query("shift_type", () => ({
			query: "custom_hr.services.employee_scope.shift_type_query",
			filters: { employee: frm.doc.employee || "" },
		}));
	},
});
