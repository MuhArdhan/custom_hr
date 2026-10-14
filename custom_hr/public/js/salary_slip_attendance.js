frappe.ui.form.on("Salary Slip", {
	refresh(frm) {
		if (frappe.session.user !== "Administrator" && !frappe.user.has_role("HR Manager") &&
			!frappe.user.has_role("System Manager")) return;
		frm.add_custom_button(__("Setup Presensi Payroll"), () => {
			frappe.set_route("List", "HRM Attendance Payroll Settings");
		});
		frm.add_custom_button(__("Preview Presensi"), () => {
			if (!frm.doc.employee || !frm.doc.start_date || !frm.doc.end_date) {
				frappe.msgprint(__("Pilih karyawan dan periode terlebih dahulu."));
				return;
			}
			frappe.call({
				method: "custom_hr.api.payroll_attendance.preview_attendance",
				args: { employee: frm.doc.employee, start_date: frm.doc.start_date, end_date: frm.doc.end_date },
				freeze: true,
				callback({ message }) {
					const preview = { rows: message.rows.map(({ category, quantity, unit, estimated_amount }) =>
						({ category, quantity, unit, estimated_amount })), warnings: message.warnings,
						blockers: message.blockers, note: "Preview tidak menyimpan. Aturan aktif diterapkan saat slip dihitung/disimpan." };
					frappe.msgprint({ title: __("Preview Presensi Payroll"), wide: true,
						message: `<pre>${frappe.utils.escape_html(JSON.stringify(preview, null, 2))}</pre>` });
				},
			});
		});
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Refresh Snapshot Presensi"), () => {
				if (frm.is_new() || frm.is_dirty()) {
					frappe.msgprint(__("Simpan slip terlebih dahulu."));
					return;
				}
				frappe.confirm(__("Hitung ulang slip dan snapshot presensi? Potongan dari aturan aktif akan diperbarui. Data belum lengkap menghalangi Submit."), () => {
					frappe.call({
						method: "custom_hr.api.payroll_attendance.save_attendance_snapshot",
						args: { salary_slip: frm.doc.name }, freeze: true,
						callback() { frm.reload_doc(); },
					});
				});
			});
		}
	},
});
