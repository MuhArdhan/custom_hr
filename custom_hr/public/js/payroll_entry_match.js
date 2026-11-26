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
	let file_meta = null;
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
	dialog.$wrapper.addClass("pm-dialog");
	const $file_wrap = dialog.fields_dict.file.$wrapper;
	const $table = dialog.fields_dict.table.$wrapper;

	function render_file_box() {
		const size_kb = file_meta ? `${Math.max(1, Math.round(file_meta.size / 1024))} KB` : "";
		const title = file_meta ? esc(file_meta.name) : __("Pilih file Excel (.xlsx)");
		const subtitle = file_meta
			? `${size_kb} · ${__("Klik untuk ganti file")}`
			: __("File hanya dibaca di browser untuk dicocokkan, tidak disimpan di server.");
		$file_wrap.html(`
			<div class="frappe-control">
				<label class="control-label">${__("File Excel (.xlsx)")}</label>
				<label class="pm-dropzone ${file_meta ? "has-file" : ""}">
					<input type="file" class="pm-file" accept=".xlsx">
					<span class="pm-drop-icon">${frappe.utils.icon(file_meta ? "file" : "upload", "md")}</span>
					<span class="pm-drop-text">
						<span class="pm-drop-title">${title}</span>
						<span class="pm-drop-sub text-muted small">${subtitle}</span>
					</span>
					<span class="btn btn-xs btn-default">${file_meta ? __("Ganti") : __("Browse")}</span>
				</label>
			</div>
		`);
		$file_wrap.find(".pm-file").on("change", (event) => read_file(event.target.files[0]));
	}

	render_file_box();
	$table.html(`<div class="pm-empty-state">${__("Pilih file Excel (.xlsx) untuk mulai membandingkan dengan slip gaji draft.")}</div>`);
	dialog.get_primary_btn().prop("disabled", true);
	dialog.show();

	function read_file(file) {
		if (!file) return;
		file_meta = { name: file.name, size: file.size };
		render_file_box();
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
		$table.html(`<div class="pm-empty-state text-muted">${__("Mencocokkan data sheet dengan slip gaji...")}</div>`);
		const args = { content, sheet, match_by, mapping_mode };
		if (custom_columns?.length) args.custom_columns = JSON.stringify(custom_columns);
		call("compare", args).then((message) => {
			result = message;
			render();
		});
	}

	function render_mapping_panel() {
		const cols = result.columns || [];
		const mode_badge =
			result.mapping_mode === "custom"
				? __("Custom")
				: result.mapping_mode === "settings"
					? __("Payroll Settings")
					: __("Otomatis");
		const tags = cols.length
			? cols
				.map(
					(c) => `<span class="pm-map-tag">
						<span>${esc(c.label)}</span>
						<span class="pm-col-code">${esc(c.key)}</span>
					</span>`
				)
				.join("")
			: `<span class="text-muted small">${__("Belum ada kolom gaji yang cocok terdeteksi.")}</span>`;

		const header_bar = `<div class="pm-map-head">
			<div class="pm-map-title">
				<b>${__("Pemetaan Kolom")}</b>
				<span class="indicator-pill gray">${cols.length} ${__("kolom")}</span>
				<span class="indicator-pill blue">${esc(mode_badge)}</span>
			</div>
			${result.header_options?.length ? `<button type="button" class="btn btn-xs btn-default pm-toggle-map">${show_mapping ? __("Tutup") : __("Ubah Pemetaan")}</button>` : ""}
		</div>`;

		if (!show_mapping) {
			return `<div class="pm-card">
				${header_bar}
				<div class="pm-map-tags">${tags}</div>
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
		(result.all_components || [])
			.filter((comp) => !mapped_comps.has(comp))
			.forEach((comp) => {
				editable_rows.push({ component: comp, key: "" });
			});

		const row_html = editable_rows
			.map((r) => {
				if (r.readonly) {
					return `<div class="pm-map-item">
						<span class="pm-map-comp">${esc(r.label)}</span>
						<input class="form-control input-xs pm-map-input" data-components='${esc(JSON.stringify(r.components))}' value="${esc(r.key)}" title="${__("Gabungan kolom pakai +, mis. AO+AQ")}">
					</div>`;
				}
				const select_opts = [
					`<option value="">${__("— Tidak dicocokkan —")}</option>`,
					...(result.header_options || []).map((o) => `<option value="${esc(o.key)}" ${o.key === r.key ? "selected" : ""}>${esc(o.label)}</option>`),
				];
				if (r.key && !(result.header_options || []).some((o) => o.key === r.key)) {
					select_opts.push(`<option value="${esc(r.key)}" selected>${esc(r.key)}</option>`);
				}
				return `<div class="pm-map-item">
					<span class="pm-map-comp">${esc(r.component)}</span>
					<select class="form-control input-xs pm-map-select" data-component="${esc(r.component)}">${select_opts.join("")}</select>
				</div>`;
			})
			.join("");

		return `<div class="pm-card">
			${header_bar}
			<div class="pm-map-edit">
				<div class="pm-map-grid">${row_html}</div>
				<div class="pm-map-actions">
					<button type="button" class="btn btn-xs btn-default pm-reset-map">${__("Reset Otomatis")}</button>
					<button type="button" class="btn btn-xs btn-primary pm-apply-map">${__("Cocokkan Ulang")}</button>
				</div>
			</div>
		</div>`;
	}

	function render_exception_section(title, color, items) {
		if (!items?.length) return "";
		return `<details class="pm-sec">
			<summary>
				<span class="pm-sec-title">
					<span class="pm-caret">${frappe.utils.icon("down", "xs")}</span>
					<span>${esc(title)}</span>
				</span>
				<span class="indicator-pill ${color}">${items.length}</span>
			</summary>
			<div class="pm-sec-body">${items.map((item) => `<span class="pm-exc-chip">${esc(item)}</span>`).join("")}</div>
		</details>`;
	}

	function render() {
		const differing = result.columns.filter((column) => result.rows.some((row) => row.cells[column.key]));
		const keyLabel = result.match_by === "name" ? __("Nama") : __("NIP");
		const diffCount = result.rows.length;
		const matchedOk = Math.max(0, result.matched - diffCount);

		const stats = `<div class="pm-toolbar">
			<div class="pm-stats">
				<div class="pm-stat"><span class="pm-stat-lbl">${__("Slip Draft")}</span><b>${result.slips}</b></div>
				<div class="pm-stat"><span class="pm-stat-lbl">${__("Cocok {0}", [keyLabel])}</span><b>${result.matched}</b></div>
				<div class="pm-stat"><span class="pm-stat-lbl">${__("Sesuai Semua")}</span><b class="pm-txt-green">${matchedOk}</b></div>
				<div class="pm-stat"><span class="pm-stat-lbl">${__("Ada Selisih")}</span><b class="${diffCount ? "pm-txt-orange" : "pm-txt-green"}">${diffCount}</b></div>
			</div>
			${
				diffCount
					? `<div class="pm-tools">
						<input type="search" class="form-control input-xs pm-search" placeholder="${__("Cari NIP atau nama...")}">
						<span class="pm-picked-pill indicator-pill blue pm-hidden"></span>
					</div>`
					: ""
			}
		</div>`;

		const head = differing
			.map((c) => `<th><div>${esc(c.label)}</div><div class="pm-th-sub">${esc(c.key)}${c.editable ? "" : ` · ${c.label.includes("+") ? __("Gabungan") : __("Input Periodik")}`}</div></th>`)
			.join("");

		const foot = differing
			.map((c) =>
				c.editable
					? `<td><button type="button" class="btn btn-xs btn-default pm-all" data-col="${esc(c.key)}">${__("Semua → Excel")}</button></td>`
					: `<td class="text-muted small">${c.label.includes("+") ? __("Gabungan, cek manual") : __("Ubah di Input Additional Salary")}</td>`
			)
			.join("");

		const body = result.rows
			.map((row) => {
				const search_key = `${row.nip || ""} ${row.employee_name || ""}`.toLowerCase();
				const cells = differing
					.map((column) => {
						const cell = row.cells[column.key];
						if (!cell) return `<td class="pm-ok" title="${__("Cocok")}">✓</td>`;
						const values = `<div class="pm-vals">
							<span class="pm-sys">${money(cell.system)}</span>
							<span class="pm-arrow">→</span>
							<span class="pm-xls">${money(cell.excel)}</span>
						</div>`;
						if (!column.editable) return `<td class="pm-cell pm-diff">${values}</td>`;
						const name = `pm-${row.slip}-${column.key}`;
						return `<td class="pm-cell pm-diff" data-slip="${esc(row.slip)}" data-col="${esc(column.key)}" data-component="${esc(column.component)}" data-amount="${cell.excel}">
							${values}
							<div class="pm-seg" role="group">
								<label class="pm-seg-opt is-active"><input type="radio" name="${esc(name)}" value="system" checked><span>${__("Sistem")}</span></label>
								<label class="pm-seg-opt"><input type="radio" name="${esc(name)}" value="excel"><span>${__("Excel")}</span></label>
							</div>
						</td>`;
					})
					.join("");
				return `<tr data-search="${esc(search_key)}">
					<td class="pm-col-nip">${esc(row.nip || "-")}</td>
					<td class="pm-col-name"><a href="/app/salary-slip/${encodeURIComponent(row.slip)}" target="_blank">${esc(row.employee_name)}</a></td>
					${cells}
				</tr>`;
			})
			.join("");

		const main_view = result.rows.length
			? `<div class="pm-table-wrap"><div class="pm-scroll"><table class="table table-bordered pm-table">
				<thead><tr><th class="pm-col-nip">${__("NIP")}</th><th class="pm-col-name">${__("Nama")}</th>${head}</tr></thead>
				<tbody>${body}</tbody>
				<tfoot><tr><td class="pm-col-nip"></td><td class="pm-col-name text-muted small">${__("Aksi Massal")}</td>${foot}</tr></tfoot>
			</table></div></div>`
			: result.matched
				? `<div class="pm-banner pm-banner-success">${frappe.utils.icon("check", "sm")} <span>${__("Semua slip yang datanya ada di sheet sudah cocok.")}</span></div>`
				: `<div class="pm-banner pm-banner-warning">${frappe.utils.icon("warning", "sm")} <span>${__("Tidak ada karyawan yang cocok antara slip dan sheet dengan mode {0}.", [keyLabel])}</span></div>`;

		const exceptions = [
			render_exception_section(__("{0} dobel di sheet, tidak dicocokkan", [keyLabel]), "orange", result.duplicates),
			render_exception_section(__("{0} dobel di slip draft, tidak dicocokkan", [keyLabel]), "orange", result.duplicate_slips || []),
			render_exception_section(__("{0} di Excel tanpa slip draft", [keyLabel]), "gray", result.not_in_slips),
			render_exception_section(
				__("Slip tanpa {0} di Excel", [keyLabel]),
				"gray",
				(result.not_in_excel || []).map((r) => `${r.employee_name} (${r.nip || __("NIP kosong")})`)
			),
		].join("");

		$table.html(`
			${render_mapping_panel()}
			${stats}
			${main_view}
			${exceptions ? `<div class="pm-exceptions">${exceptions}</div>` : ""}
		`);

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
		$table.find(".pm-search").on("input", (event) => {
			const q = (event.currentTarget.value || "").trim().toLowerCase();
			$table.find("tbody tr").each((_, tr) => $(tr).toggle(!q || tr.dataset.search.includes(q)));
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
		$table.find("td[data-slip]").each((_, td) => {
			const $td = $(td);
			const excel_picked = $td.find("input[value=excel]").is(":checked");
			$td.toggleClass("is-picked", excel_picked);
			$td.find(".pm-seg-opt").each((__, opt) => {
				$(opt).toggleClass("is-active", $(opt).find("input").is(":checked"));
			});
		});
		const count = picked().length;
		const $pill = $table.find(".pm-picked-pill");
		if ($pill.length) {
			$pill.toggleClass("pm-hidden", !count).text(count ? __("{0} sel dipilih", [count]) : "");
		}
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
		.pm-dialog .modal-dialog { max-width: min(1240px, 95vw); }
		.pm-hidden { display: none !important; }
		.pm-dropzone {
			display: flex; align-items: center; gap: 10px; margin: 0; padding: 10px 12px;
			background: var(--subtle-fg); border: 1px dashed var(--border-color);
			border-radius: var(--border-radius-md, 8px); cursor: pointer; font-weight: normal;
			transition: border-color 0.15s ease, background 0.15s ease;
		}
		.pm-dropzone:hover { border-color: var(--gray-500); background: var(--fg-hover-color); }
		.pm-dropzone.has-file { border-style: solid; background: var(--control-bg); }
		.pm-dropzone input[type="file"] { display: none; }
		.pm-drop-icon { color: var(--text-muted); display: inline-flex; flex: none; }
		.pm-drop-text { flex: 1; min-width: 0; display: flex; flex-direction: column; }
		.pm-drop-title { font-weight: 500; color: var(--text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
		.pm-empty-state {
			padding: 36px 16px; text-align: center; color: var(--text-muted);
			background: var(--subtle-fg); border: 1px dashed var(--border-color);
			border-radius: var(--border-radius-md, 8px);
		}
		.pm-card {
			background: var(--card-bg); border: 1px solid var(--border-color);
			border-radius: var(--border-radius-md, 8px); padding: 10px 12px; margin-bottom: 12px;
		}
		.pm-map-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
		.pm-map-title { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: var(--text-sm); }
		.pm-map-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
		.pm-map-tag {
			display: inline-flex; align-items: center; gap: 5px;
			background: var(--subtle-fg); border: 1px solid var(--border-color);
			border-radius: var(--border-radius-sm, 6px); padding: 2px 7px; font-size: var(--text-xs);
		}
		.pm-col-code {
			font-family: var(--font-stack-monospace, monospace); font-weight: 600;
			color: var(--text-muted); background: var(--card-bg); padding: 0 4px; border-radius: 3px;
		}
		.pm-map-edit { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border-color); }
		.pm-map-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 8px 12px; }
		.pm-map-item { display: flex; flex-direction: column; gap: 3px; }
		.pm-map-comp { font-size: var(--text-xs); font-weight: 600; color: var(--text-muted); }
		.pm-map-actions { display: flex; justify-content: flex-end; gap: 6px; margin-top: 10px; }
		.pm-toolbar {
			display: flex; align-items: center; justify-content: space-between; gap: 10px;
			flex-wrap: wrap; margin-bottom: 10px;
		}
		.pm-stats { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
		.pm-stat {
			display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px;
			background: var(--subtle-fg); border: 1px solid var(--border-color);
			border-radius: var(--border-radius-sm, 6px); font-size: var(--text-xs);
			font-variant-numeric: tabular-nums;
		}
		.pm-stat-lbl { color: var(--text-muted); }
		.pm-txt-green { color: var(--green-600); }
		.pm-txt-orange { color: var(--orange-600); }
		.pm-tools { display: flex; align-items: center; gap: 8px; }
		.pm-search { width: 220px; }
		.pm-table-wrap {
			border: 1px solid var(--border-color); border-radius: var(--border-radius-md, 8px);
			overflow: hidden; background: var(--card-bg);
		}
		.pm-scroll { max-height: 52vh; overflow: auto; }
		.pm-table { margin: 0; font-size: var(--text-sm); white-space: nowrap; border-collapse: separate; border-spacing: 0; }
		.pm-table th, .pm-table td { border-color: var(--border-color) !important; vertical-align: middle; padding: 7px 10px; }
		.pm-table thead th {
			position: sticky; top: 0; z-index: 2; background: var(--subtle-fg);
			color: var(--text-color); font-weight: 600; font-size: var(--text-xs);
		}
		.pm-th-sub { font-weight: 400; color: var(--text-muted); font-size: 11px; margin-top: 1px; }
		.pm-table tfoot td { position: sticky; bottom: 0; z-index: 2; background: var(--subtle-fg); }
		.pm-col-nip { position: sticky; left: 0; z-index: 1; width: 92px; min-width: 92px; max-width: 92px; overflow: hidden; text-overflow: ellipsis; background: var(--card-bg); font-variant-numeric: tabular-nums; }
		.pm-col-name { position: sticky; left: 92px; z-index: 1; min-width: 185px; background: var(--card-bg); box-shadow: 2px 0 4px -2px rgba(0, 0, 0, 0.08); }
		.pm-table thead th.pm-col-nip, .pm-table thead th.pm-col-name,
		.pm-table tfoot td.pm-col-nip, .pm-table tfoot td.pm-col-name { z-index: 4; background: var(--subtle-fg); }
		.pm-table tbody tr:hover td.pm-col-nip, .pm-table tbody tr:hover td.pm-col-name,
		.pm-table tbody tr:hover td.pm-ok { background: var(--fg-hover-color); }
		.pm-ok { color: var(--green-600); text-align: center; font-weight: 600; opacity: 0.75; }
		.pm-cell { font-variant-numeric: tabular-nums; }
		.pm-diff { background: var(--subtle-fg); box-shadow: inset 3px 0 0 var(--orange-500); }
		.pm-diff.is-picked { background: var(--control-bg); box-shadow: inset 3px 0 0 var(--blue-500); }
		.pm-vals { display: flex; align-items: center; gap: 5px; font-size: var(--text-xs); }
		.pm-sys { color: var(--text-muted); }
		.pm-arrow { color: var(--text-light); }
		.pm-xls { font-weight: 600; color: var(--text-color); }
		.pm-diff.is-picked .pm-sys { text-decoration: line-through; opacity: 0.7; }
		.pm-diff.is-picked .pm-xls { color: var(--blue-600); }
		.pm-seg {
			display: inline-flex; margin-top: 4px; padding: 2px;
			background: var(--card-bg); border: 1px solid var(--border-color);
			border-radius: var(--border-radius-sm, 6px); gap: 2px;
		}
		.pm-seg-opt { margin: 0; font-weight: normal; cursor: pointer; display: inline-flex; }
		.pm-seg-opt input { display: none; }
		.pm-seg-opt span { padding: 1px 8px; border-radius: 4px; font-size: 11px; color: var(--text-muted); }
		.pm-seg-opt.is-active span { background: var(--subtle-fg); color: var(--text-color); font-weight: 600; }
		.pm-diff.is-picked .pm-seg-opt.is-active span { background: var(--blue-500); color: #fff; }
		.pm-banner {
			display: flex; align-items: center; gap: 8px; padding: 12px 14px;
			border-radius: var(--border-radius-md, 8px); border: 1px solid var(--border-color);
			font-size: var(--text-sm); font-weight: 500;
		}
		.pm-banner-success { background: var(--subtle-fg); color: var(--green-600); border-left: 3px solid var(--green-500); }
		.pm-banner-warning { background: var(--subtle-fg); color: var(--orange-600); border-left: 3px solid var(--orange-500); }
		.pm-exceptions { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
		.pm-sec { border: 1px solid var(--border-color); border-radius: var(--border-radius-md, 8px); background: var(--card-bg); }
		.pm-sec summary {
			cursor: pointer; list-style: none; padding: 7px 10px; font-size: var(--text-xs); font-weight: 600;
			display: flex; align-items: center; justify-content: space-between; gap: 8px;
		}
		.pm-sec summary::-webkit-details-marker { display: none; }
		.pm-sec summary:hover { background: var(--subtle-fg); }
		.pm-sec-title { display: inline-flex; align-items: center; gap: 6px; }
		.pm-caret { display: inline-flex; color: var(--text-muted); transition: transform 0.15s ease; }
		.pm-sec:not([open]) .pm-caret { transform: rotate(-90deg); }
		.pm-sec-body {
			padding: 8px 10px; border-top: 1px solid var(--border-color);
			display: flex; flex-wrap: wrap; gap: 5px; max-height: 150px; overflow: auto;
		}
		.pm-exc-chip {
			background: var(--subtle-fg); border: 1px solid var(--border-color);
			border-radius: 4px; padding: 2px 7px; font-size: 11px; color: var(--text-color);
		}
	`;
	document.head.appendChild(style);
}
