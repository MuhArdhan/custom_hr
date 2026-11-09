// Shared by the Payroll Entry list (Bulk Create Payroll Entry) and the Salary Slip list (Bulk Submit Salary Slip).

const BULK_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

// same periods as Input Payroll Periode: the one named after a month ends on its 25th
function bulk_payroll_periods() {
	const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
	const current = new Date(today.getFullYear(), today.getMonth() + (today.getDate() > 25 ? 1 : 0), 1);
	return Array.from({ length: 13 }, (_, i) => {
		const d = new Date(current.getFullYear(), current.getMonth() - i + 1, 1);
		return { value: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`, label: `${BULK_MONTHS[d.getMonth()]} ${d.getFullYear()}` };
	});
}

// Run the native Payroll Entry for many companies of one period (create), or submit their draft slips (submit).
function open_bulk_payroll(mode, list_view) {
	const esc = frappe.utils.escape_html;
	const create = mode === "create";
	const periods = bulk_payroll_periods();
	const action = create ? __("Create Payroll Entry") : __("Submit Salary Slip");
	const money = (value) => format_currency(value || 0, frappe.boot.sysdefaults.currency, 0);
	let selected = new Set();
	let rows = [];

	bulk_payroll_style();
	const dialog = new frappe.ui.Dialog({
		title: create ? __("Bulk Create Payroll Entry") : __("Bulk Submit Salary Slip"),
		size: "large",
		fields: [
			{ fieldname: "month", fieldtype: "Select", label: __("Period"), options: periods, default: periods[1].value, change: () => load() },
			{ fieldname: "col", fieldtype: "Column Break" },
			{ fieldname: "search", fieldtype: "Data", label: __("Search Company"), placeholder: __("Type a company name") },
			{ fieldname: "sec", fieldtype: "Section Break" },
			{ fieldname: "targets", fieldtype: "HTML" },
		],
		primary_action_label: action,
		primary_action: run,
	});
	const $box = dialog.fields_dict.targets.$wrapper;
	const month = () => dialog.get_value("month") || periods[1].value; // the Select may not have its default yet
	dialog.fields_dict.search.$input.on("input", filter);

	// "2026-11" -> "26 Oct 2026 – 25 Nov 2026", the same cut-off as Input Payroll Periode
	function period_text(value) {
		const [year, mon] = value.split("-").map(Number);
		const fmt = (d) => `${d.getDate()} ${BULK_MONTHS[d.getMonth()].slice(0, 3)} ${d.getFullYear()}`;
		return `${fmt(new Date(year, mon - 2, 26))} – ${fmt(new Date(year, mon - 1, 25))}`;
	}

	function filter() {
		const query = (dialog.get_value("search") || "").trim().toLowerCase();
		$box.find(".bp-row").each((_, row) => $(row).toggle(!query || row.dataset.label.includes(query)));
		sync_all();
	}

	function sync_all() {
		const all = $box.find(".bp-all").get(0);
		if (!all) return;
		const boxes = $box.find(".bp-ready .bp-row:visible input").get();
		const on = boxes.filter((input) => input.checked).length;
		all.checked = boxes.length > 0 && on === boxes.length;
		all.indeterminate = on > 0 && on < boxes.length;
	}

	function summarize() {
		const picked = rows.filter((row) => selected.has(row.name));
		const count = picked.reduce((sum, row) => sum + (create ? row.employees : row.slips), 0);
		const text = !selected.size
			? __("Nothing selected")
			: create
				? __("Selected: {0} · Employees: {1}", [selected.size, count])
				: __("Selected: {0} · Slips: {1} · Net Pay: {2}", [selected.size, count, money(picked.reduce((sum, row) => sum + row.net_pay, 0))]);
		$box.find(".bp-summary").text(text);
		dialog.set_primary_action(selected.size ? `${action} (${selected.size})` : action, run);
		dialog.get_primary_btn().prop("disabled", !selected.size);
		sync_all();
	}

	function row_html(row, blocked, twice) {
		// the payable account only matters when one company has two entries
		const sub = twice.has(row.company) && row.account ? `<div class="bp-sub">${esc(row.account.replace(/ - [^-]+$/, ""))}</div>` : "";
		const right = blocked
			? `<span class="bp-reason${row.done ? " bp-done" : ""}">${esc(row.reason)}</span>`
			: create
				? `<span class="bp-num">${row.employees}</span>`
				: `<span class="bp-num">${row.slips}</span><span class="bp-num bp-money">${money(row.net_pay)}</span>`;
		return `<label class="bp-row" data-label="${esc(row.company.toLowerCase())}">
			${blocked ? "" : `<input type="checkbox" data-name="${esc(row.name)}">`}
			<div class="bp-name"><div>${esc(row.company)}</div>${sub}</div>${right}
		</label>`;
	}

	async function load() {
		const period = month();
		dialog.set_df_property("month", "description", period_text(period));
		selected = new Set();
		rows = [];
		$box.html(`<div class="bp-empty">${__("Loading...")}</div>`);
		summarize();
		const { message } = await frappe.call({ method: "custom_hr.api.payroll_bulk.get_bulk_targets", type: "GET", args: { month: period, mode } });
		if (month() !== period) return; // a newer period superseded this one
		rows = message;
		if (!rows.length) {
			$box.html(`<div class="bp-empty">${create ? __("No employees with a Salary Structure Assignment in this period.") : __("No draft salary slips in this period. Create them first with Bulk Create Payroll Entry in the Payroll Entry list.")}</div>`);
			return summarize();
		}
		const counts = {};
		rows.forEach((row) => (counts[row.company] = (counts[row.company] || 0) + 1));
		const twice = new Set(Object.keys(counts).filter((company) => counts[company] > 1));
		const ready = rows.filter((row) => !(create && row.reason));
		const blocked = rows.filter((row) => create && row.reason);
		const head = create
			? `<span class="bp-num">${__("Employees")}</span>`
			: `<span class="bp-num">${__("Slips")}</span><span class="bp-num bp-money">${__("Net Pay")}</span>`;
		$box.html(`
			${ready.length
				? `<div class="bp-table bp-ready">
					<label class="bp-head"><input type="checkbox" class="bp-all"><div class="bp-name">${__("Select all ({0})", [ready.length])}</div>${head}</label>
					<div class="bp-list">${ready.map((row) => row_html(row, false, twice)).join("")}</div>
				</div>`
				: `<div class="bp-empty">${__("Every company in this period is already created or not ready.")}</div>`}
			${blocked.length
				? `<details class="bp-blocked"${ready.length ? "" : " open"}>
					<summary>${__("Not available ({0})", [blocked.length])}</summary>
					<div class="bp-table"><div class="bp-list">${blocked.map((row) => row_html(row, true, twice)).join("")}</div></div>
				</details>`
				: ""}
			<div class="bp-summary"></div>`);
		$box.find(".bp-all").on("change", (event) => {
			$box.find(".bp-ready .bp-row:visible input").each((_, input) => {
				input.checked = event.target.checked;
				selected[input.checked ? "add" : "delete"](input.dataset.name);
			});
			summarize();
		});
		$box.find(".bp-ready .bp-list").on("change", "input", (event) => {
			selected[event.target.checked ? "add" : "delete"](event.target.dataset.name);
			summarize();
		});
		filter();
		summarize();
	}

	function run() {
		if (!selected.size) return frappe.msgprint(__("Select at least one company."));
		const count = selected.size;
		const question = create
			? __("Create a Payroll Entry with draft salary slips for each of the {0} selected?", [count])
			: __("Submit every draft salary slip of the {0} selected? The payroll payable journal is booked and the slips can no longer be edited.", [count]);
		frappe.confirm(question, async () => {
			const period = month();
			const companies = Object.fromEntries(rows.map((row) => [row.name, `${row.company} · ${row.account || "-"}`]));
			const targets = [...selected];
			const failed = [];
			dialog.hide();
			// one company per request, so the progress is real and one failure does not stop the rest
			for (const [i, target] of targets.entries()) {
				frappe.show_progress(dialog.title, i, targets.length, esc(companies[target] || target), true);
				let error;
				try {
					const { message } = await frappe.call({
						method: `custom_hr.api.payroll_bulk.${create ? "create_payroll_entry" : "submit_payroll_entry"}`,
						args: { month: period, target },
					});
					error = message;
				} catch {
					error = __("Request failed");
				}
				if (error) failed.push(`<li><b>${esc(companies[target] || target)}</b>: ${esc(error)}</li>`);
			}
			frappe.hide_progress();
			frappe.msgprint({
				title: dialog.title,
				indicator: failed.length ? "orange" : "green",
				message: __("Succeeded: {0} · Failed: {1}", [targets.length - failed.length, failed.length]) + (failed.length ? `<ul>${failed.join("")}</ul>` : ""),
			});
			list_view.refresh();
		});
	}

	dialog.show();
	load();
}

function bulk_payroll_style() {
	if (document.getElementById("bulk-payroll-style")) return;
	$("<style id='bulk-payroll-style'>").text(`
		.bp-table { border: 1px solid var(--border-color); border-radius: 8px; overflow: hidden; }
		.bp-list { max-height: 45vh; overflow: auto; }
		.bp-head, .bp-row { display: flex; align-items: center; gap: 10px; padding: 8px 12px; margin: 0; font-weight: normal; }
		.bp-head { background: var(--subtle-fg); font-size: 12px; font-weight: 600; color: var(--text-muted); border-bottom: 1px solid var(--border-color); cursor: pointer; }
		.bp-row { border-bottom: 1px solid var(--border-color); cursor: pointer; }
		.bp-row:last-child { border-bottom: none; }
		.bp-row:hover { background: var(--subtle-accent); }
		.bp-head input, .bp-row input { margin: 0; flex: none; }
		.bp-name { flex: 1; min-width: 0; }
		.bp-sub { font-size: 11px; color: var(--text-muted); }
		.bp-num { width: 72px; text-align: right; font-variant-numeric: tabular-nums; flex: none; }
		.bp-money { width: 130px; }
		.bp-reason { color: var(--red-600); font-size: 12px; text-align: right; }
		.bp-reason.bp-done { color: var(--green-600); }
		.bp-blocked { margin-top: 12px; }
		.bp-blocked summary { cursor: pointer; color: var(--text-muted); font-size: 13px; margin-bottom: 8px; }
		.bp-blocked .bp-row { cursor: default; padding-left: 12px; }
		.bp-summary { margin-top: 12px; font-weight: 600; }
		.bp-empty { padding: 24px; text-align: center; color: var(--text-muted); border: 1px dashed var(--border-color); border-radius: 8px; }
	`).appendTo("head");
}
