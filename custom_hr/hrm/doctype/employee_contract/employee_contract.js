function get_contract_duration_end(doc) {
	const months = { "3 bulan": 3, "6 bulan": 6, "12 bulan": 12, "24 bulan": 24 }[doc.contract_duration];
	if (doc.contract_type !== "PKWT" || !doc.start_date || !months) return null;
	return frappe.datetime.add_days(frappe.datetime.add_months(doc.start_date, months), -1);
}

function update_contract_duration_end(frm) {
	if (frm.doc.docstatus !== 0) return;
	const end_date = get_contract_duration_end(frm.doc);
	if (end_date) return frm.set_value("end_date", end_date);
}

frappe.ui.form.on("Employee Contract", {
	contract_duration: update_contract_duration_end,
	start_date: update_contract_duration_end,
	end_date(frm) {
		if (frm.doc.docstatus !== 0) return;
		const expected = get_contract_duration_end(frm.doc);
		if (expected && frm.doc.end_date && frm.doc.end_date !== expected) {
			return frm.set_value("contract_duration", "Custom");
		}
	},
	async contract_type(frm) {
		if (frm.doc.docstatus !== 0) return;
		if (frm.doc.contract_type === "PKWTT") {
			await frm.set_value("contract_duration", "Custom");
			await frm.set_value("end_date", null);
		} else {
			await update_contract_duration_end(frm);
		}
	},
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.contract_type === "PKWT") {
			frm.add_custom_button(__("Buat Perpanjangan"), () => {
				frappe.call({
					method: "custom_hr.hrm.doctype.employee_contract.employee_contract.get_renewal_defaults",
					args: { contract: frm.doc.name },
					callback({ message }) {
						frappe.new_doc("Employee Contract", message, (doc) => {
							// Route defaults skip no_copy fields; explicitly link this renewal.
							doc.previous_contract = message.previous_contract;
						});
					},
				});
			});
		}
		if (!frm.is_new()) {
			frm.add_custom_button(__("Riwayat Kontrak Karyawan"), () => {
				frappe.set_route("List", "Employee Contract", { employee: frm.doc.employee });
			});
		}
		frm.set_query("previous_contract", () => ({
			filters: { employee: frm.doc.employee, docstatus: 1, contract_type: "PKWT" },
		}));
	},
});
