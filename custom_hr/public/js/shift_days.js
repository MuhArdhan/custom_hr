// Hari column of the Outlet Shift table (Outlet "shifts", Department "auto_shifts"): a click opens
// day checkboxes and writes "Senin, Rabu, Minggu". The server still checks it (services.outlet_shift.parse_days).
frappe.provide("custom_hr");

custom_hr.SHIFT_DAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"];

// Weekday indexes (0 = Senin) of a Hari value: "Senin-Kamis", "Jumat", "Senin, Rabu"; empty or "Setiap hari" = all.
// Unknown text gives null, so the dialog starts empty instead of guessing.
custom_hr.shift_days_from_text = function (text) {
	const value = (text || "").trim().toLowerCase();
	if (!value || value === "setiap hari") return [0, 1, 2, 3, 4, 5, 6];
	const names = custom_hr.SHIFT_DAYS.map((day) => day.toLowerCase());
	const days = new Set();
	for (const part of value.split(",")) {
		const ends = part.split(/\s*[-–]\s*/).map((end) => names.indexOf(end.trim()));
		if (ends.length > 2 || ends.includes(-1)) return null;
		const [first, last] = [ends[0], ends[ends.length - 1]];
		for (let step = 0; step <= (last - first + 7) % 7; step++) days.add((first + step) % 7); // a range may wrap past Minggu
	}
	return [...days].sort();
};

custom_hr.shift_days_to_text = function (days) {
	return days.length === 7 ? "Setiap hari" : days.map((day) => custom_hr.SHIFT_DAYS[day]).join(", ");
};

custom_hr.setup_shift_days = function (frm, table_fieldname) {
	const grid = frm.fields_dict[table_fieldname]?.grid;
	if (!grid || grid.custom_hr_days) return;
	grid.custom_hr_days = true;
	// mousedown, not click: once the row is in edit mode the grid redraws it between mousedown and
	// mouseup, so no click ever fires. focusin covers reaching the cell with Tab. Capture phase: the
	// grid row's own handlers stop the event before it would bubble up here.
	const open = (event) => {
		const cell = event.target.closest('[data-fieldname="days"]');
		if (!cell || frm.fields_dict[table_fieldname].df.read_only || frm.doc.docstatus !== 0) return;
		// closing the dialog hands focus back to the cell: that focus must not reopen it
		if (event.type === "focusin" && Date.now() - (custom_hr.shift_days_closed_at || 0) < 600) return;
		const name = cell.closest(".grid-row")?.getAttribute("data-name");
		const row = name && locals["Outlet Shift"][name];
		if (!row) return;
		event.preventDefault(); // no focus or typing in the cell: the dialog writes it
		event.target.blur?.();
		custom_hr.pick_shift_days(row);
	};
	grid.wrapper[0].addEventListener("mousedown", open, true);
	grid.wrapper[0].addEventListener("focusin", open, true);
};

custom_hr.pick_shift_days = function (row) {
	if (custom_hr.shift_days_dialog_open) return; // mousedown and the focus it causes would open it twice
	custom_hr.shift_days_dialog_open = true;
	const current = custom_hr.shift_days_from_text(row.days) || [];
	const dialog = new frappe.ui.Dialog({
		title: __("Hari berlaku: {0}", [row.shift_type || __("shift")]),
		fields: [
			{
				fieldname: "days",
				fieldtype: "MultiCheck",
				columns: 3,
				sort_options: false, // keep Senin..Minggu, not alphabetical
				options: custom_hr.SHIFT_DAYS.map((label, index) => ({ label, value: String(index), checked: current.includes(index) })),
			},
		],
		primary_action_label: __("Simpan"),
		primary_action(values) {
			const days = (values.days || []).map(Number).sort();
			if (!days.length) {
				frappe.msgprint(__("Pilih minimal satu hari."));
				return;
			}
			frappe.model.set_value(row.doctype, row.name, "days", custom_hr.shift_days_to_text(days));
			dialog.hide();
		},
	});
	dialog.onhide = () => {
		custom_hr.shift_days_dialog_open = false;
		custom_hr.shift_days_closed_at = Date.now();
	};
	dialog.show();
};

frappe.ui.form.on("Outlet", { refresh: (frm) => custom_hr.setup_shift_days(frm, "shifts") });
frappe.ui.form.on("Department", {
	refresh: (frm) => custom_hr.setup_shift_days(frm, "auto_shifts"),
	// one shift mode at a time, like the Outlet: ticking one clears the other
	enable_auto_shift(frm) {
		if (frm.doc.enable_auto_shift && frm.doc.manual_shift_choice) frm.set_value("manual_shift_choice", 0);
	},
	manual_shift_choice(frm) {
		if (frm.doc.manual_shift_choice && frm.doc.enable_auto_shift) frm.set_value("enable_auto_shift", 0);
	},
});
