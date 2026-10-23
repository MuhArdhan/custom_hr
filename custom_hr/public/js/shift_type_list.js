// HRMS defines the Shift Type list settings (Shift Tools group); extend them instead of replacing.
const hrms_list_settings = frappe.listview_settings["Shift Type"] || {};

frappe.listview_settings["Shift Type"] = {
	...hrms_list_settings,
	onload(list_view) {
		hrms_list_settings.onload?.(list_view);
		list_view.page.add_inner_button(__("Atur Outlet"), open_outlet_dialog, __("Shift Tools"));
	},
};

function open_outlet_dialog() {
	const esc = frappe.utils.escape_html;
	let initial = {}; // outlet -> already had the shift when the list was loaded
	let selected = new Set();

	const changes = () => ({
		add: Object.keys(initial).filter((name) => !initial[name] && selected.has(name)),
		remove: Object.keys(initial).filter((name) => initial[name] && !selected.has(name)),
	});

	const dialog = new frappe.ui.Dialog({
		title: __("Atur Outlet per Shift"),
		size: "large",
		fields: [
			{
				fieldname: "shift_type",
				fieldtype: "Link",
				options: "Shift Type",
				label: __("Shift Type"),
				reqd: 1,
				change: () => load(),
			},
			{ fieldname: "search", fieldtype: "Data", label: __("Cari Outlet") },
			{ fieldname: "outlets", fieldtype: "HTML" },
		],
		primary_action_label: __("Simpan"),
		primary_action: save,
	});
	const $box = dialog.fields_dict.outlets.$wrapper;

	function summarize() {
		const { add, remove } = changes();
		$box.find(".so-summary").text(
			__("{0} outlet dipilih · tambah {1} · hapus {2}", [selected.size, add.length, remove.length])
		);
	}

	function filter() {
		const query = (dialog.fields_dict.search.$input.val() || "").trim().toLowerCase();
		$box.find(".so-row").each((_, row) => {
			$(row).toggle(!query || row.dataset.name.toLowerCase().includes(query));
		});
	}

	function set_visible(checked) {
		$box.find(".so-row:visible input").each((_, input) => {
			input.checked = checked;
			selected[checked ? "add" : "delete"](input.dataset.name);
		});
		summarize();
	}

	async function load() {
		const shift_type = dialog.get_value("shift_type");
		initial = {};
		selected = new Set();
		$box.empty();
		if (!shift_type) return;
		const { message } = await frappe.call({
			method: "custom_hr.api.outlet.get_shift_outlets",
			args: { shift_type },
		});
		if (dialog.get_value("shift_type") !== shift_type) return; // a newer choice superseded this one
		message.forEach((row) => {
			initial[row.outlet] = !!row.has_shift;
			if (row.has_shift) selected.add(row.outlet);
		});
		$box.html(`
			<div class="so-toolbar" style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
				<button type="button" class="btn btn-xs btn-default so-all">${__("Pilih yang tampil")}</button>
				<button type="button" class="btn btn-xs btn-default so-none">${__("Hapus centang yang tampil")}</button>
				<span class="so-summary text-muted"></span>
			</div>
			<div class="so-list" style="max-height:45vh;overflow:auto;padding:0 4px">
				${message
					.map(
						(row) => `<label class="so-row" data-name="${esc(row.outlet)}" style="display:flex;gap:8px;align-items:center;padding:3px 0;margin:0">
							<input type="checkbox" data-name="${esc(row.outlet)}" ${row.has_shift ? "checked" : ""}>
							<span>${esc(row.outlet)}</span>
						</label>`
					)
					.join("")}
			</div>`);
		$box.find(".so-all").on("click", () => set_visible(true));
		$box.find(".so-none").on("click", () => set_visible(false));
		$box.find(".so-list").on("change", "input", (event) => {
			selected[event.target.checked ? "add" : "delete"](event.target.dataset.name);
			summarize();
		});
		filter();
		summarize();
	}

	async function apply(shift_type, { add, remove }) {
		dialog.hide();
		const { message: result } = await frappe.call({
			method: "custom_hr.api.outlet.set_shift_outlets",
			args: { shift_type, add, remove },
			freeze: true,
		});
		const failed = result.failed.map((row) => `<li>${esc(row.outlet)}: ${esc(row.error)}</li>`);
		frappe.msgprint({
			title: __("Selesai"),
			indicator: failed.length ? "orange" : "green",
			message:
				__("Ditambahkan: {0}, dihapus: {1}, tidak berubah: {2}, gagal: {3}", [
					result.added,
					result.removed,
					result.unchanged,
					failed.length,
				]) + (failed.length ? `<ul>${failed.join("")}</ul>` : ""),
		});
	}

	function save() {
		const shift_type = dialog.get_value("shift_type");
		const diff = changes();
		if (!shift_type || !(diff.add.length || diff.remove.length)) {
			frappe.msgprint(__("Tidak ada perubahan untuk disimpan."));
			return;
		}
		if (!diff.remove.length) return apply(shift_type, diff);
		frappe.confirm(
			__("{0} outlet akan kehilangan shift {1}. Lanjutkan?", [diff.remove.length, esc(shift_type)]),
			() => apply(shift_type, diff)
		);
	}

	dialog.show();
	dialog.fields_dict.search.$input.on("input", filter);
}
