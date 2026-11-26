const base_ea_list = frappe.listview_settings["Employee Advance"] || {};

frappe.listview_settings["Employee Advance"] = {
	...base_ea_list,
	onload(list_view) {
		base_ea_list.onload?.(list_view);
		if (frappe.model.can_submit("Additional Salary") && frappe.model.can_read("Employee Advance")) {
			list_view.page.add_inner_button(__("Bulk Deduct from Salary"), () => open_bulk_advance_deduct(list_view));
		}
	},
};

function open_bulk_advance_deduct(list_view) {
	const esc = frappe.utils.escape_html;
	const money = (value, currency) => format_currency(value || 0, currency || frappe.boot.sysdefaults.currency, 0);
	const checked = new Set(list_view.get_checked_items(true) || []);
	let rows = [];
	let selected = new Set();

	advance_bulk_style();
	const dialog = new frappe.ui.Dialog({
		title: __("Bulk Deduct from Salary"),
		size: "large",
		fields: [
			{
				fieldname: "salary_component",
				fieldtype: "Link",
				label: __("Salary Component"),
				options: "Salary Component",
				reqd: 1,
				placeholder: __("Pilih komponen potongan"),
				get_query: () => ({ filters: { type: "Deduction", disabled: 0 } }),
				change: summarize,
			},
			{ fieldname: "col1", fieldtype: "Column Break" },
			{ fieldname: "payroll_date", fieldtype: "Date", label: __("Payroll Date"), reqd: 1, change: summarize },
			{ fieldname: "col2", fieldtype: "Column Break" },
			{ fieldname: "search", fieldtype: "Data", label: __("Search"), placeholder: __("Nama, ID, company, atau YYYY-MM") },
			{ fieldname: "sec", fieldtype: "Section Break" },
			{ fieldname: "targets", fieldtype: "HTML" },
		],
		primary_action_label: __("Create & Submit"),
		primary_action: run,
	});

	const $box = dialog.fields_dict.targets.$wrapper;
	dialog.fields_dict.search.$input.on("input", filter);

	function filter() {
		const query = (dialog.get_value("search") || "").trim().toLowerCase();
		$box.find(".eab-row").each((_, el) => $(el).toggle(!query || el.dataset.search.includes(query)));
		sync_all();
	}

	function sync_all() {
		const all = $box.find(".eab-all").get(0);
		if (!all) return;
		const visible = $box.find(".eab-row:visible input").get();
		const on = visible.filter((el) => el.checked).length;
		all.checked = visible.length > 0 && on === visible.length;
		all.indeterminate = on > 0 && on < visible.length;
	}

	function summarize() {
		const picked = rows.filter((r) => selected.has(r.name));
		const total = picked.reduce((acc, r) => acc + r.remaining_amount, 0);
		const ready = Boolean(picked.length && dialog.get_value("salary_component") && dialog.get_value("payroll_date"));
		$box.find(".eab-summary").text(
			picked.length ? __("Selected: {0} · Total: {1}", [picked.length, money(total, picked[0]?.currency)]) : __("Nothing selected")
		);
		dialog.set_primary_action(picked.length ? `${__("Create & Submit")} (${picked.length})` : __("Create & Submit"), run);
		dialog.get_primary_btn().prop("disabled", !ready);
		sync_all();
	}

	function render() {
		if (!rows.length) {
			$box.html(`<div class="eab-empty">${__("Tidak ada Employee Advance berstatus Paid (Repay from Salary) yang belum dijadwalkan potong gajinya.")}</div>`);
			summarize();
			return;
		}
		const items = rows
			.map((r) => {
				const posting_month = frappe.datetime.str_to_obj(r.posting_date).toLocaleDateString("id-ID", { month: "short", year: "numeric" });
				const search = `${r.name} ${r.employee_name || ""} ${r.company || ""} ${r.posting_date || ""} ${posting_month}`.toLowerCase();
				const is_checked = selected.has(r.name) ? " checked" : "";
				return `<label class="eab-row" data-search="${esc(search)}">
					<input type="checkbox" data-name="${esc(r.name)}"${is_checked}>
					<div class="eab-main">
						<div><b>${esc(r.employee_name || r.employee)}</b> <span class="text-muted small">(${esc(r.name)})</span></div>
						<div class="text-muted small">${esc(r.company)} · ${esc(frappe.datetime.str_to_user(r.posting_date))} (${esc(posting_month)})</div>
					</div>
					<div class="eab-amt">${money(r.remaining_amount, r.currency)}</div>
				</label>`;
			})
			.join("");
		$box.html(`
			<div class="eab-bar">
				<label class="eab-checkall"><input type="checkbox" class="eab-all"> ${__("Select all")}</label>
				<span class="eab-summary text-muted small"></span>
			</div>
			<div class="eab-list">${items}</div>
		`);
		$box.find(".eab-all").on("change", (ev) => {
			$box.find(".eab-row:visible input").each((_, el) => {
				el.checked = ev.currentTarget.checked;
				selected[ev.currentTarget.checked ? "add" : "delete"](el.dataset.name);
			});
			summarize();
		});
		$box.on("change", ".eab-row input", (ev) => {
			selected[ev.currentTarget.checked ? "add" : "delete"](ev.currentTarget.dataset.name);
			summarize();
		});
		filter();
		summarize();
	}

	function run() {
		const salary_component = dialog.get_value("salary_component");
		const payroll_date = dialog.get_value("payroll_date");
		const advances = rows.filter((r) => selected.has(r.name)).map((r) => r.name);
		if (!salary_component || !payroll_date || !advances.length) return;
		dialog.get_primary_btn().prop("disabled", true);
		frappe
			.call({
				method: "custom_hr.api.advance_bulk.bulk_deduct_from_salary",
				args: { advances, salary_component, payroll_date },
				freeze: true,
				freeze_message: __("Membuat Additional Salary..."),
			})
			.then(({ message }) => {
				const ok = (message?.created || []).length;
				const recalc = message?.recalculated || 0;
				const err = message?.errors || [];
				if (ok) {
					const msg = recalc
						? __("{0} Additional Salary berhasil dibuat & disubmit ({1} slip draft dihitung ulang)", [ok, recalc])
						: __("{0} Additional Salary berhasil dibuat dan disubmit", [ok]);
					frappe.show_alert({ message: msg, indicator: "green" });
				}
				if (err.length) {
					frappe.msgprint({
						title: __("Sebagian Gagal"),
						indicator: "orange",
						message: err.map((e) => `<div><b>${esc(e.name)}:</b> ${esc(e.error)}</div>`).join(""),
					});
				}
				dialog.hide();
				list_view.refresh();
			})
			.catch(() => dialog.get_primary_btn().prop("disabled", false));
	}

	$box.html(`<div class="eab-empty">${__("Loading...")}</div>`);
	dialog.show();
	dialog.get_primary_btn().prop("disabled", true);

	frappe.call({ method: "custom_hr.api.advance_bulk.get_deduct_targets", type: "GET" }).then(({ message }) => {
		rows = message?.advances || [];
		if (message?.default_component) dialog.set_value("salary_component", message.default_component);
		if (message?.default_payroll_date) dialog.set_value("payroll_date", message.default_payroll_date);
		selected = checked.size
			? new Set(rows.filter((r) => checked.has(r.name)).map((r) => r.name))
			: new Set();
		render();
	});
}

function advance_bulk_style() {
	if (document.getElementById("advance-bulk-style")) return;
	const style = document.createElement("style");
	style.id = "advance-bulk-style";
	style.textContent = `
		.eab-bar { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
		.eab-checkall { display:flex; align-items:center; gap:6px; margin:0; font-weight:600; cursor:pointer; }
		.eab-list { max-height:48vh; overflow:auto; border:1px solid var(--border-color); border-radius:var(--border-radius); }
		.eab-row { display:flex; align-items:center; gap:10px; padding:8px 12px; border-bottom:1px solid var(--border-color); margin:0; cursor:pointer; }
		.eab-row:last-child { border-bottom:0; }
		.eab-row:hover { background:var(--fg-hover-color); }
		.eab-main { flex:1; min-width:0; }
		.eab-amt { font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap; }
		.eab-empty { padding:24px 0; text-align:center; color:var(--text-muted); }
	`;
	document.head.appendChild(style);
}
