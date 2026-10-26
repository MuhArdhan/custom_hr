const hrms_list_settings = frappe.listview_settings["Holiday List Assignment"] || {};

frappe.listview_settings["Holiday List Assignment"] = {
	...hrms_list_settings,
	onload(list_view) {
		hrms_list_settings.onload?.(list_view);
		list_view.page.add_inner_button(__("Bulk Assign"), open_assign_dialog);
	},
};

// Assign a Holiday List to many Companies/Employees at once. Targets already on it show checked and
// locked; this only adds assignments, it never removes one.
function open_assign_dialog() {
	const esc = frappe.utils.escape_html;
	let selected = new Set();

	const dialog = new frappe.ui.Dialog({
		title: __("Bulk Assign Holiday List"),
		size: "large",
		fields: [
			{ fieldname: "holiday_list", fieldtype: "Link", options: "Holiday List", label: __("Holiday List"), reqd: 1, change: () => load() },
			{
				fieldname: "kind",
				fieldtype: "Select",
				options: ["Company", "Employee"],
				default: "Company",
				label: __("Applicable For"),
				change: () => load(),
			},
			{ fieldname: "from_date", fieldtype: "Date", label: __("From Date"), reqd: 1, default: frappe.datetime.year_start() },
			{ fieldname: "search", fieldtype: "Data", label: __("Search") },
			{ fieldname: "targets", fieldtype: "HTML" },
		],
		primary_action_label: __("Assign"),
		primary_action: save,
	});
	const $box = dialog.fields_dict.targets.$wrapper;
	dialog.fields_dict.search.$input.on("input", filter);

	function filter() {
		const query = (dialog.fields_dict.search.$input.val() || "").trim().toLowerCase();
		$box.find(".ha-row").each((_, row) => $(row).toggle(!query || row.dataset.label.includes(query)));
	}

	function summarize() {
		$box.find(".ha-summary").text(__("{0} selected", [selected.size]));
	}

	function set_visible(checked) {
		$box.find(".ha-row:visible input:not(:disabled)").each((_, input) => {
			input.checked = checked;
			selected[checked ? "add" : "delete"](input.dataset.name);
		});
		summarize();
	}

	async function load() {
		const kind = dialog.get_value("kind") || "Company"; // the Select may not have its default yet
		const holiday_list = dialog.get_value("holiday_list");
		selected = new Set();
		$box.empty();
		if (!holiday_list) return;
		const { message } = await frappe.call({
			method: "custom_hr.api.holiday.get_holiday_targets",
			args: { holiday_list, kind },
		});
		if ((dialog.get_value("kind") || "Company") !== kind || dialog.get_value("holiday_list") !== holiday_list) return; // a newer choice superseded this one
		$box.html(`
			<div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
				<button type="button" class="btn btn-xs btn-default ha-all">${__("Select visible")}</button>
				<button type="button" class="btn btn-xs btn-default ha-none">${__("Uncheck visible")}</button>
				<span class="ha-summary text-muted"></span>
			</div>
			<div class="ha-list" style="max-height:50vh;overflow:auto;padding:0 4px">
				${message
					.map(
						(row) => `<label class="ha-row" data-label="${esc(row.label.toLowerCase())}" style="display:flex;gap:8px;align-items:center;padding:3px 0;margin:0">
							<input type="checkbox" data-name="${esc(row.name)}" ${row.on_list ? "checked disabled" : ""}>
							<span>${esc(row.label)}</span>
							<span class="text-muted" style="margin-left:auto">${row.on_list ? "" : esc(row.holiday_list || __("none"))}</span>
						</label>`
					)
					.join("")}
			</div>`);
		$box.find(".ha-all").on("click", () => set_visible(true));
		$box.find(".ha-none").on("click", () => set_visible(false));
		$box.find(".ha-list").on("change", "input", (event) => {
			selected[event.target.checked ? "add" : "delete"](event.target.dataset.name);
			summarize();
		});
		filter();
		summarize();
	}

	async function save() {
		if (!selected.size) return frappe.msgprint(__("Select at least one."));
		const values = dialog.get_values();
		const holiday_list = values.holiday_list;
		values.kind = values.kind || "Company";
		dialog.hide();
		const { message: result } = await frappe.call({
			method: "custom_hr.api.holiday.assign_holiday_list",
			args: { holiday_list, kind: values.kind, targets: [...selected], from_date: values.from_date },
			freeze: true,
		});
		const failed = result.failed.map((row) => `<li>${esc(row.target)}: ${esc(row.error)}</li>`);
		frappe.msgprint({
			title: __("Result"),
			indicator: failed.length ? "orange" : "green",
			message:
				__("Assigned: {0} · unchanged: {1} · failed: {2}", [result.assigned, result.unchanged, failed.length]) +
				(failed.length ? `<ul>${failed.join("")}</ul>` : ""),
		});
	}

	dialog.show();
}
