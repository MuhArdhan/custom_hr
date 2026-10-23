// HRMS defines the Shift Type list settings (Shift Tools group); extend them instead of replacing.
const hrms_list_settings = frappe.listview_settings["Shift Type"] || {};

frappe.listview_settings["Shift Type"] = {
	...hrms_list_settings,
	onload(list_view) {
		hrms_list_settings.onload?.(list_view);
		list_view.page.add_inner_button(__("Atur Outlet"), open_outlet_dialog, __("Shift Tools"));
	},
};

// Partition the outlets by what the dialog shows: still connected, to be added, to be removed.
function outlet_groups(initial, selected) {
	const names = Object.keys(initial);
	return {
		connected: names.filter((name) => initial[name] && selected.has(name)),
		add: names.filter((name) => !initial[name] && selected.has(name)),
		remove: names.filter((name) => initial[name] && !selected.has(name)),
	};
}

function open_outlet_dialog() {
	const esc = frappe.utils.escape_html;
	let initial = {}; // outlet -> already had the shift when the list was loaded
	let selected = new Set();

	const changes = () => {
		const { add, remove } = outlet_groups(initial, selected);
		return { add, remove };
	};

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
		const { connected, add, remove } = outlet_groups(initial, selected);
		$box.find(".so-summary").text(
			__("{0} outlet dipilih · tambah {1} · hapus {2}", [selected.size, add.length, remove.length])
		);

		const chips = (names, background) =>
			names
				.map(
					(name) =>
						`<span style="display:inline-block;margin:2px 4px 2px 0;padding:1px 8px;border-radius:10px;font-size:12px;background:${background}">${esc(name)}</span>`
				)
				.join("");
		const group = (title, names, background) =>
			`<div style="margin-bottom:6px"><b>${title} (${names.length}):</b> ${
				names.length ? chips(names, background) : '<span class="text-muted">—</span>'
			}</div>`;
		$box.find(".so-names").html(
			group(__("Tersambung"), connected, "var(--gray-200)") +
				(add.length ? group(__("Akan ditambah"), add, "#dcfce7") : "") +
				(remove.length ? group(__("Akan dihapus"), remove, "#fee2e2") : "")
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
			<div class="so-names" style="max-height:140px;overflow:auto;margin-bottom:8px;padding:0 4px"></div>
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
