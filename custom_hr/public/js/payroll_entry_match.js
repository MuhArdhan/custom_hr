// Cocokkan Gaji: compare HR's salary sheet with this entry's draft slips, and take the Excel value cell by cell.
// The file is read in the browser and sent with each request; it is never saved as a File.

const MATCH_METHOD = "custom_hr.api.payroll_match";
const MATCH_MONTHS = ["JANUARI", "FEBRUARI", "MARET", "APRIL", "MEI", "JUNI", "JULI", "AGUSTUS", "SEPTEMBER", "OKTOBER", "NOVEMBER", "DESEMBER"];

frappe.ui.form.on("Payroll Entry", {
	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Cocokkan dengan Excel"), () => open_payroll_match(frm));
		}
	},
});

function open_payroll_match(frm) {
	const esc = frappe.utils.escape_html;
	const money = (value) => format_currency(value || 0, frm.doc.currency, 0);
	let content = null;
	let result = null;
	let custom_columns = null;
	let show_mapping = false;

	payroll_match_style();
	const dialog = new frappe.ui.Dialog({
		title: __("Cocokkan Gaji dengan Excel"),
		size: "extra-large",
		fields: [
			{ fieldname: "file", fieldtype: "HTML" },
			{ fieldname: "col", fieldtype: "Column Break" },
			{
				fieldname: "match_by",
				fieldtype: "Select",
				label: __("Cocokkan Berdasarkan"),
				options: [
					{ value: "nip", label: __("NIP") },
					{ value: "name", label: __("Nama") },
				],
				default: "nip",
				change: () => run_compare(),
			},
			{
				fieldname: "mapping_mode",
				fieldtype: "Select",
				label: __("Sumber Kolom"),
				options: [
					{ value: "auto", label: __("Otomatis dari Header") },
					{ value: "settings", label: __("Manual (Payroll Settings)") },
				],
				default: "auto",
				change: () => {
					custom_columns = null;
					run_compare();
				},
			},
			{ fieldname: "sheet", fieldtype: "Select", label: __("Sheet"), hidden: 1, change: () => { custom_columns = null; run_compare(); } },
			{ fieldname: "sec", fieldtype: "Section Break" },
			{ fieldname: "table", fieldtype: "HTML" },
		],
		primary_action_label: __("Terapkan"),
		primary_action: apply,
	});
	const $table = dialog.fields_dict.table.$wrapper;
	dialog.fields_dict.file.$wrapper.html(`
		<label class="control-label">${__("File Excel (.xlsx)")}</label>
		<input type="file" class="form-control pm-file" accept=".xlsx">
		<p class="help-box small text-muted">${__("File hanya dibaca untuk dicocokkan, tidak disimpan di sistem.")}</p>`);
	dialog.fields_dict.file.$wrapper.find(".pm-file").on("change", (event) => read_file(event.target.files[0]));
	dialog.get_primary_btn().prop("disabled", true);
	dialog.show();

	function read_file(file) {
		if (!file) return;
		custom_columns = null;
		show_mapping = false;
		const reader = new FileReader();
		reader.onload = () => {
			content = reader.result.split(",")[1];
			dialog.set_value("sheet", "");
			call("compare", { content }).then((message) => {
				if (!message?.sheets) return;
				// the sheet named after the entry's month is the usual pick, e.g. "OKTOBER 2026"
				const month = MATCH_MONTHS[frappe.datetime.str_to_obj(frm.doc.end_date).getMonth()];
				const field = dialog.fields_dict.sheet;
				field.df.options = message.sheets;
				field.df.hidden = 0;
				field.refresh();
				dialog.set_value("sheet", message.sheets.find((name) => name.toUpperCase().includes(month)) || message.sheets[0]);
			});
		};
		reader.readAsDataURL(file);
	}

	function call(method, args) {
		return frappe
			.call({ method: `${MATCH_METHOD}.${method}`, args: { payroll_entry: frm.doc.name, ...args }, freeze: true })
			.then((r) => r.message);
	}

	function run_compare() {
		const sheet = dialog.get_value("sheet");
		const match_by = dialog.get_value("match_by") || "nip";
		const mapping_mode = dialog.get_value("mapping_mode") || "auto";
		if (!content || !sheet) return;
		dialog.get_primary_btn().prop("disabled", true);
		$table.empty();
		const args = { content, sheet, match_by, mapping_mode };
		if (custom_columns?.length) args.custom_columns = JSON.stringify(custom_columns);
		call("compare", args).then((message) => {
			result = message;
			render();
		});
	}

	function render_mapping_panel() {
		const cols = result.columns || [];
		const pills = cols.length
			? cols.map((c) => `<span class="pm-pill">${esc(c.label)} <b>→ ${esc(c.key)}</b></span>`).join(" ")
			: `<span class="text-muted small">${__("Belum ada kolom gaji yang cocok terdeteksi.")}</span>`;
		if (!show_mapping) {
			return `<div class="pm-map-bar">
				<div><b>${__("Pemetaan Kolom")}:</b> ${pills}</div>
				${result.header_options?.length ? `<button class="btn btn-xs btn-default pm-toggle-map">${__("Ubah Pemetaan")}</button>` : ""}
			</div>`;
		}
		const editable_rows = [];
		cols.forEach((c) => {
			if (c.components?.length === 1) {
				editable_rows.push({ component: c.components[0], key: c.key });
			} else {
				editable_rows.push({ label: c.label, key: c.key, readonly: true, components: c.components });
			}
		});
		const mapped_comps = new Set(cols.flatMap((c) => c.components || []));
		(result.all_components || []).filter((comp) => !mapped_comps.has(comp)).forEach((comp) => {
			editable_rows.push({ component: comp, key: "" });
		});
		const row_html = editable_rows.map((r) => {
			if (r.readonly) {
				return `<div class="pm-map-item"><span class="pm-map-comp">${esc(r.label)}</span><input class="form-control input-xs pm-map-input" data-components='${esc(JSON.stringify(r.components))}' value="${esc(r.key)}" title="${__("Gabungan kolom pakai +, mis. AO+AQ")}"></div>`;
			}
			const select_opts = [`<option value="">${__("— Tidak dicocokkan —")}</option>`, ...(result.header_options || []).map((o) => `<option value="${esc(o.key)}" ${o.key === r.key ? "selected" : ""}>${esc(o.label)}</option>`)];
			if (r.key && !(result.header_options || []).some((o) => o.key === r.key)) {
				select_opts.push(`<option value="${esc(r.key)}" selected>${esc(r.key)}</option>`);
			}
			return `<div class="pm-map-item"><span class="pm-map-comp">${esc(r.component)}</span><select class="form-control input-xs pm-map-select" data-component="${esc(r.component)}">${select_opts.join("")}</select></div>`;
		}).join("");
		return `<div class="pm-map-box">
			<div class="pm-map-bar">
				<b>${__("Sesuaikan Pemetaan Kolom Excel")}</b>
				<div>
					<button class="btn btn-xs btn-default pm-reset-map">${__("Reset Otomatis")}</button>
					<button class="btn btn-xs btn-primary pm-apply-map">${__("Cocokkan Ulang")}</button>
					<button class="btn btn-xs btn-default pm-toggle-map">${__("Tutup")}</button>
				</div>
			</div>
			<div class="pm-map-grid">${row_html}</div>
		</div>`;
	}

	function render() {
		const differing = result.columns.filter((column) => result.rows.some((row) => row.cells[column.key]));
		const keyLabel = result.match_by === "name" ? __("Nama") : __("NIP");
		const summary = __("{0} slip draft · {1} cocok {2} · {3} karyawan ada yang beda", [result.slips, result.matched, keyLabel, result.rows.length]);
		const head = differing
			.map((c) => `<th>${esc(c.label)}<div class="text-muted small">${esc(c.key)}</div></th>`)
			.join("");
		const foot = differing
			.map((c) =>
				c.editable
					? `<td><button class="btn btn-xs btn-default pm-all" data-col="${esc(c.key)}">${__("Semua → Excel")}</button></td>`
					: `<td class="text-muted small">${c.label.includes("+") ? __("Gabungan, cek manual") : __("Ubah di Input Additional Salary")}</td>`
			)
			.join("");
		const body = result.rows
			.map((row) => {
				const cells = differing
					.map((column) => {
						const cell = row.cells[column.key];
						if (!cell) return `<td class="pm-ok">✓</td>`;
						const values = `<div>${money(cell.system)} ⇄ ${money(cell.excel)}</div>`;
						if (!column.editable) return `<td class="pm-diff">${values}</td>`;
						const name = `pm-${row.slip}-${column.key}`;
						return `<td class="pm-diff" data-slip="${esc(row.slip)}" data-col="${esc(column.key)}" data-component="${esc(column.component)}" data-amount="${cell.excel}">${values}
							<label><input type="radio" name="${esc(name)}" value="system" checked> ${__("Sistem")}</label>
							<label><input type="radio" name="${esc(name)}" value="excel"> ${__("Excel")}</label></td>`;
					})
					.join("");
				return `<tr><td>${esc(row.nip)}</td><td><a href="/app/salary-slip/${encodeURIComponent(row.slip)}" target="_blank">${esc(row.employee_name)}</a></td>${cells}</tr>`;
			})
			.join("");
		const only = (title, items) =>
			items.length ? `<p class="small"><b>${title} (${items.length}):</b> ${items.map(esc).join(", ")}</p>` : "";
		$table.html(`
			${render_mapping_panel()}
			<p>${summary}</p>
			${
				result.rows.length
					? `<div class="pm-scroll"><table class="table table-bordered pm-table">
						<thead><tr><th>NIP</th><th>${__("Nama")}</th>${head}</tr></thead>
						<tbody>${body}</tbody>
						<tfoot><tr><td colspan="2"></td>${foot}</tr></tfoot></table></div>`
					: result.matched
						? `<p class="text-success">${__("Semua slip yang datanya ada di sheet sudah cocok.")}</p>`
						: `<p class="text-warning">${__("Tidak ada karyawan yang cocok antara slip dan sheet dengan mode {0}.", [keyLabel])}</p>`
			}
			${only(__("{0} dobel di sheet, tidak dicocokkan", [keyLabel]), result.duplicates)}
			${only(__("{0} dobel di slip draft, tidak dicocokkan", [keyLabel]), result.duplicate_slips || [])}
			${only(__("{0} di Excel tanpa slip draft", [keyLabel]), result.not_in_slips)}
			${only(__("Slip tanpa {0} di Excel", [keyLabel]), result.not_in_excel.map((r) => `${r.employee_name} (${r.nip || __("NIP kosong")})`))}`);
		$table.find(".pm-toggle-map").on("click", () => { show_mapping = !show_mapping; render(); });
		$table.find(".pm-reset-map").on("click", () => { custom_columns = null; show_mapping = false; run_compare(); });
		$table.find(".pm-apply-map").on("click", () => {
			const next = [];
			$table.find(".pm-map-input").each((_, el) => {
				const col = ($(el).val() || "").trim();
				if (!col) return;
				JSON.parse(el.dataset.components || "[]").forEach((comp) => next.push({ excel_column: col, salary_component: comp }));
			});
			$table.find(".pm-map-select").each((_, el) => {
				const col = ($(el).val() || "").trim();
				if (col) next.push({ excel_column: col, salary_component: el.dataset.component });
			});
			if (!next.length) {
				frappe.msgprint(__("Pilih minimal satu kolom untuk dicocokkan."));
				return;
			}
			custom_columns = next;
			show_mapping = false;
			run_compare();
		});
		$table.find(".pm-all").on("click", (event) => {
			$table.find(`td[data-col="${event.currentTarget.dataset.col}"] input[value=excel]`).prop("checked", true);
			sync();
		});
		$table.find("input[type=radio]").on("change", sync);
		sync();
	}

	function picked() {
		return $table
			.find("td[data-slip]")
			.filter((_, td) => $(td).find("input[value=excel]").is(":checked"))
			.map((_, td) => ({ slip: td.dataset.slip, column: td.dataset.col, component: td.dataset.component, amount: flt(td.dataset.amount) }))
			.get();
	}

	function sync() {
		const count = picked().length;
		dialog.set_primary_action(count ? __("Terapkan ({0})", [count]) : __("Terapkan"), apply);
		dialog.get_primary_btn().prop("disabled", !count);
	}

	function apply() {
		const changes = picked();
		if (!changes.length) return;
		frappe.confirm(__("Ambil nilai Excel untuk {0} sel? Tiap sel menjadi Additional Salary yang menimpa hasil rumus.", [changes.length]), () =>
			call("apply", { changes }).then((message) => {
				frappe.show_alert({ message: __("{0} sel diterapkan ke {1} slip", [message.applied, message.slips]), indicator: "green" });
				run_compare(); // the same file again: applied cells now match and drop out
			})
		);
	}
}

function payroll_match_style() {
	if (document.getElementById("payroll-match-style")) return;
	const style = document.createElement("style");
	style.id = "payroll-match-style";
	style.textContent = `
		.pm-scroll { max-height: 60vh; overflow: auto; }
		.pm-table { font-size: var(--text-sm); white-space: nowrap; }
		.pm-table thead th { position: sticky; top: 0; background: var(--card-bg); }
		.pm-table .pm-ok { color: var(--text-muted); text-align: center; }
		.pm-table .pm-diff { background: var(--bg-orange); }
		.pm-table label { margin: 0 8px 0 0; font-weight: normal; }
		.pm-map-bar { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
		.pm-pill { display: inline-block; background: var(--subtle-fg); border-radius: 4px; padding: 2px 6px; font-size: var(--text-xs); margin: 2px 2px 2px 0; }
		.pm-map-box { background: var(--subtle-fg); border-radius: 6px; padding: 10px; margin-bottom: 10px; }
		.pm-map-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 8px; }
		.pm-map-item { display: flex; flex-direction: column; gap: 2px; }
		.pm-map-comp { font-size: var(--text-xs); font-weight: 600; }`;
	document.head.appendChild(style);
}
