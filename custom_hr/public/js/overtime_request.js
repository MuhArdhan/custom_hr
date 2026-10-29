frappe.listview_settings["Overtime Request"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colors = {
			"Menunggu Leader": "orange",
			"Menunggu SPV": "yellow",
			"Menunggu HRD": "blue",
			Disetujui: "green",
			Ditolak: "red",
		};
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},
};

frappe.ui.form.on("Overtime Request", {
	async setup(frm) {
		frm._allowed_outlets = await frappe
			.xcall("custom_hr.api.roster.list_outlets")
			.catch(() => []);
		frm.set_query("outlet", () => {
			return { filters: { name: ["in", frm._allowed_outlets] } };
		});
		frm.set_query("employee", "employees", () => {
			const filters = { status: "Active" };
			if (frm.doc.outlet) {
				filters.outlet = frm.doc.outlet;
			}
			return { filters };
		});
	},
	onload(frm) {
		if (frm.is_new() && !frm.doc.overtime_type) {
			frm.set_value("overtime_type", "Lembur");
		}
	},
	refresh(frm) {
		if (!frm.is_new()) {
			frm.set_intro(__("Approve atau tolak lembur per karyawan di Working Calendar."), "blue");
		}
	},
	start_time: update_planned_hours,
	end_time: update_planned_hours,
});

function update_planned_hours(frm) {
	const { start_time, end_time } = frm.doc;
	if (!start_time || !end_time) return;
	const [sh, sm] = start_time.split(":").map(Number);
	const [eh, em] = end_time.split(":").map(Number);
	let hours = (eh * 60 + em - (sh * 60 + sm)) / 60;
	if (hours <= 0) hours += 24;
	frm.doc.planned_hours = Math.round(hours * 100) / 100;
	frm.refresh_field("planned_hours");
}
