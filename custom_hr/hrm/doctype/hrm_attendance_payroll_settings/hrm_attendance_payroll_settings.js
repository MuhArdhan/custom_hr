frappe.ui.form.on("HRM Attendance Payroll Settings", {
	refresh(frm) {
		frm.set_query("salary_component", "rules", () => ({ filters: { type: "Deduction", disabled: 0 } }));
		frm.add_custom_button(__("Preview Karyawan"), () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Simpan aturan terlebih dahulu."));
				return;
			}
			const end = frappe.datetime.add_days(frappe.datetime.get_today(), -1);
			frappe.prompt([
				{ fieldname: "employee", label: __("Karyawan"), fieldtype: "Link", options: "Employee", reqd: 1,
					get_query: () => ({ filters: { company: frm.doc.company } }) },
				{ fieldname: "start_date", label: __("Tanggal Mulai"), fieldtype: "Date", default: `${end.slice(0, 8)}01`, reqd: 1 },
				{ fieldname: "end_date", label: __("Tanggal Akhir"), fieldtype: "Date", default: end, reqd: 1 },
			], (values) => {
				frappe.call({
					method: "custom_hr.api.payroll_attendance.preview_attendance", args: values, freeze: true,
					callback({ message }) {
						const preview = { employee: message.employee, rows: message.rows.map(({ category, quantity, unit, estimated_amount }) =>
							({ category, quantity, unit, estimated_amount })), warnings: message.warnings,
							blockers: message.blockers, note: "Preview saja. Aturan aktif mengisi potongan saat Salary Slip dihitung/disimpan, tanpa Additional Salary." };
						frappe.msgprint({ title: __("Preview Presensi Payroll"), wide: true,
							message: `<pre>${frappe.utils.escape_html(JSON.stringify(preview, null, 2))}</pre>` });
					},
				});
			}, __("Preview Presensi Payroll"), __("Preview"));
		});
	},
});
