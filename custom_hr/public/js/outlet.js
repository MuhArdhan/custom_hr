frappe.listview_settings["Outlet"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Sinkron dari Company"), () => {
			frappe.confirm(
				__(
					"Buat data Outlet untuk semua leaf Company di luar JURI GROUP, PT. JUARA ROTI INDONESIA, OUTLET, TRAINING, dan OUTLET PAMERAN?"
				),
				() => {
					frappe.call({
						method: "custom_hr.api.outlet.sync_outlets_from_companies",
						freeze: true,
						callback: (r) => {
							if (!r.exc) {
								frappe.show_alert({
									message: __("Outlet baru dibuat: {0}", [r.message.created]),
									indicator: "green",
								});
								listview.refresh();
							}
						},
					});
				}
			);
		});
	},
};

frappe.ui.form.on("Outlet", {
	refresh(frm) {
		frm.set_intro(
			__(
				"Pengaturan shift outlet masih tahap persiapan. Mode otomatis belum dapat diaktifkan sampai integrasi absen selesai. Jeda Peralihan IN bukan toleransi terlambat; toleransi tetap diatur pada Shift Type."
			),
			"orange"
		);
		if (frm.is_new()) return;
		frm.add_custom_button(__("Provision Karyawan"), () => {
			frappe.call({
				method: "custom_hr.api.outlet.provision_outlet",
				args: { outlet: frm.doc.name },
				freeze: true,
				callback: (r) => {
					if (!r.exc) {
						frappe.msgprint(
							__("Karyawan diproses: {0}, libur di-assign: {1}", [
								r.message.employees,
								r.message.holidays_assigned,
							])
						);
					}
				},
			});
		});
	},
});
