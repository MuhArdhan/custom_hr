frappe.ui.form.off("Salary Structure", "open_salary_slip");

frappe.ui.form.on("Salary Structure", {
	refresh(frm) {
		if (!frm.doc.is_master_template || frm.doc.docstatus !== 1 || frm.doc.is_active !== "Yes") {
			return;
		}
		frm.add_custom_button(__("Terapkan ke Company / Outlet"), () => {
			openTemplateDialog(frm);
		}, __("Template Master"));
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

function openTemplateDialog(frm) {
	let current = { prefix: "", missing: [], existing: [] };

	const dialog = new frappe.ui.Dialog({
		title: __("Terapkan Template Master"),
		fields: [
			{
				fieldname: "scope",
				fieldtype: "Select",
				label: __("Target Company yang Belum Punya"),
				options: [
					{ value: "outlets", label: __("Hanya Outlet yang belum punya") },
					{ value: "all", label: __("Semua Company yang belum punya") },
				],
				default: "outlets",
			},
			{ fieldname: "summary_html", fieldtype: "HTML" },
			{
				fieldname: "companies",
				fieldtype: "MultiCheck",
				label: __("Buat Baru untuk Company"),
				columns: 2,
				options: [],
			},
			{
				fieldname: "sync_existing",
				fieldtype: "Check",
				label: __("Perbarui komponen & rumus pada struktur turunan yang sudah ada"),
				default: 0,
			},
		],
		primary_action_label: __("Terapkan"),
		primary_action(values) {
			const create_companies = values.companies || [];
			const sync_existing = values.sync_existing ? 1 : 0;
			if (!create_companies.length && !sync_existing) {
				frappe.msgprint(__("Pilih minimal satu company baru atau centang perbarui struktur yang sudah ada."));
				return;
			}
			frappe.call({
				method: "custom_hr.services.salary_structure_template.apply_template",
				args: {
					template_name: frm.doc.name,
					create_companies,
					sync_existing,
				},
				freeze: true,
				freeze_message: __("Memproses struktur gaji..."),
				callback(r) {
					if (!r.message) return;
					dialog.hide();
					const created = r.message.created || [];
					const updated = r.message.updated || [];
					frappe.msgprint({
						title: __("Selesai"),
						indicator: "green",
						message: __("Dibuat baru: {0} struktur<br>Diperbarui: {1} struktur", [created.length, updated.length]),
					});
					frm.reload_doc();
				},
			});
		},
	});

	function loadTargets(scope) {
		frappe.call({
			method: "custom_hr.services.salary_structure_template.get_replication_targets",
			args: { template_name: frm.doc.name, scope },
			callback(r) {
				if (!r.message) return;
				current = r.message;
				const missing = current.missing || [];
				const existing = current.existing || [];
				dialog.fields_dict.summary_html.$wrapper.html(
					`<div class="text-muted small" style="margin-bottom:8px;">` +
						__("Awalan nama: <b>{0} - &lt;Company&gt;</b> &middot; Belum punya: <b>{1}</b> &middot; Sudah ada: <b>{2}</b>", [
							frappe.utils.escape_html(current.prefix || ""),
							missing.length,
							existing.length,
						]) +
						`</div>`
				);
				const ctrl = dialog.fields_dict.companies;
				ctrl.df.options = missing.map((c) => ({ label: c, value: c, checked: 1 }));
				ctrl.refresh();
				dialog.set_df_property("companies", "hidden", missing.length === 0 ? 1 : 0);
				dialog.set_df_property(
					"sync_existing",
					"label",
					__("Perbarui komponen & rumus pada {0} struktur turunan yang sudah ada", [existing.length])
				);
				dialog.set_df_property("sync_existing", "hidden", existing.length === 0 ? 1 : 0);
			},
		});
	}

	dialog.fields_dict.scope.$input.on("change", () => {
		loadTargets(dialog.get_value("scope"));
	});
	dialog.show();
	loadTargets("outlets");
}
