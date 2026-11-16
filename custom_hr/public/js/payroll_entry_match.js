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

	payroll_match_style();
	const dialog = new frappe.ui.Dialog({
		title: __("Cocokkan Gaji dengan Excel"),
		size: "extra-large",
		fields: [
			{ fieldname: "file", fieldtype: "HTML" },
			{ fieldname: "col", fieldtype: "Column Break" },
			{ fieldname: "sheet", fieldtype: "Select", label: __("Sheet"), hidden: 1, change: () => run_compare() },
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
		if (!content || !sheet) return;
		call("compare", { content, sheet }).then((message) => {
			result = message;
			render();
		});
	}

	function render() {
		const differing = result.columns.filter((column) => result.rows.some((row) => row.cells[column.key]));
		const summary = __("{0} slip draft · {1} cocok NIP · {2} karyawan ada yang beda", [result.slips, result.matched, result.rows.length]);
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
						return `<td class="pm-diff" data-slip="${esc(row.slip)}" data-col="${esc(column.key)}" data-amount="${cell.excel}">${values}
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
			<p>${summary}</p>
			${
				result.rows.length
					? `<div class="pm-scroll"><table class="table table-bordered pm-table">
						<thead><tr><th>NIP</th><th>${__("Nama")}</th>${head}</tr></thead>
						<tbody>${body}</tbody>
						<tfoot><tr><td colspan="2"></td>${foot}</tr></tfoot></table></div>`
					: `<p class="text-success">${__("Semua slip yang NIP-nya ada di sheet sudah cocok.")}</p>`
			}
			${only(__("NIP dobel di sheet, tidak dicocokkan"), result.duplicates)}
			${only(__("NIP di Excel tanpa slip draft"), result.not_in_slips)}
			${only(__("Slip tanpa NIP di Excel"), result.not_in_excel.map((r) => `${r.employee_name} (${r.nip || __("NIP kosong")})`))}`);
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
			.map((_, td) => ({ slip: td.dataset.slip, column: td.dataset.col, amount: flt(td.dataset.amount) }))
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
		.pm-table label { margin: 0 8px 0 0; font-weight: normal; }`;
	document.head.appendChild(style);
}
