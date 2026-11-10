frappe.pages["payroll-period-input"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Input Additional Salary"), single_column: true });
	frappe.payroll_period_input = new PayrollPeriodInput(page);
};

const PPI_MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"];

class PayrollPeriodInput {
	constructor(page) {
		this.page = page;
		this.page.main.addClass("ppi-page");
		this.data = null;
		this.request_id = 0;
		this.saving = Promise.resolve();
		this.pending = 0;

		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.make_filters();
		this.$summary = $('<div class="ppi-summary"></div>').appendTo(this.page.main);
		this.$table = $('<div class="ppi-table-wrap"></div>').appendTo(this.page.main);
		this.$table.on("input", "input.ppi-cell", (event) => this.edited(event.currentTarget));
		this.$table.on("change", "input.ppi-cell", (event) => this.autosave(event.currentTarget));
		this.refresh();
	}

	periods() {
		// the period named after a month ends on its 25th, so from the 26th on we are in next month's period
		const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
		const current = new Date(today.getFullYear(), today.getMonth() + (today.getDate() > 25 ? 1 : 0), 1);
		return Array.from({ length: 13 }, (_, i) => {
			const d = new Date(current.getFullYear(), current.getMonth() - i + 1, 1);
			const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
			return { value, label: `${PPI_MONTHS[d.getMonth()]} ${d.getFullYear()}` };
		});
	}

	make_filters() {
		const $filters = $('<div class="ppi-filters"></div>').appendTo(this.page.main);
		this.controls = {};
		const doc = {};
		const add = (fieldname, df) => {
			const $wrapper = $(`<div class="ppi-filter"></div>`).appendTo($filters);
			const control = frappe.ui.form.make_control({ df: { fieldname, ...df }, parent: $wrapper, doc, render_input: true });
			control.refresh();
			this.controls[fieldname] = control;
		};
		const periods = this.periods();
		this.default_month = periods[1].value; // set_value lands after the first refresh
		add("month", { label: __("Periode"), fieldtype: "Select", options: periods, default: periods[1].value, change: () => this.refresh() });
		this.controls.month.set_value(periods[1].value);
		add("company", { label: __("Company"), fieldtype: "Link", options: "Company", placeholder: __("Semua Company"), change: () => this.refresh() });
		add("search", { label: __("Cari"), fieldtype: "Data", placeholder: __("Nama atau ID karyawan") });
		this.controls.search.$input.on("input", frappe.utils.debounce(() => this.refresh(), 450));
	}

	args() {
		const value = (name) => this.controls[name].get_value() || null;
		return { month: value("month") || this.default_month, company: value("company"), search: value("search") };
	}

	async refresh() {
		await this.saving;
		const request_id = ++this.request_id;
		this.$table.html(`<div class="ppi-empty">${__("Memuat...")}</div>`);
		try {
			const { message } = await frappe.call({ method: "custom_hr.api.payroll_input.get_period_input", type: "GET", args: this.args() });
			if (request_id !== this.request_id) return;
			this.data = message;
			this.render();
		} catch {
			if (request_id === this.request_id) this.$table.html(`<div class="ppi-empty">${__("Gagal memuat data.")}</div>`);
		}
	}

	render() {
		const esc = frappe.utils.escape_html;
		const { rows, components } = this.data;
		this.$summary.empty();
		if (!components.length) {
			this.$table.html(`<div class="ppi-empty">${__("Belum ada Salary Component yang dicentang Tampil di Input Additional Salary.")}</div>`);
			return;
		}
		if (!rows.length) {
			this.$table.html(`<div class="ppi-empty">${__("Tidak ada karyawan dengan Salary Structure Assignment di periode ini.")}</div>`);
			return;
		}
		const earnings = components.filter((c) => c.type !== "Deduction");
		const deductions = components.filter((c) => c.type === "Deduction");
		const ordered = [...earnings, ...deductions];
		const ATT = [["hadir", __("Hadir")], ["telat", __("Telat")], ["pulang_cepat", __("Pulang Cepat")], ["tidak_out", __("Tidak OUT")]];
		const colspan = 1 + ATT.length + ordered.length;

		const cell = (row, c) => {
			const value = row.amounts[c.name];
			const locked = row.locked || value.multiple;
			const title = row.locked ? __("Slip periode ini sudah disubmit") : value.multiple ? __("Lebih dari satu Additional Salary, rapikan dari daftarnya") : "";
			return `<td class="ppi-amount ${c.type === "Deduction" ? "ppi-col-ded" : "ppi-col-earn"}"><input class="ppi-cell" type="text" inputmode="numeric"
				data-employee="${esc(row.employee)}" data-component="${esc(c.name)}" data-original="${value.amount || 0}"
				value="${this.fmt(value.amount)}" placeholder="–" ${locked ? "disabled" : ""} title="${esc(title)}"></td>`;
		};
		let company = null;
		const body = rows.map((row) => {
			const att = row.attendance || {};
			const group = row.company !== company
				? `<tr class="ppi-group"><td colspan="${colspan}"><span>${esc(row.company)}</span><span class="ppi-group-count">${__("{0} karyawan", [rows.filter((r) => r.company === row.company).length])}</span></td></tr>`
				: "";
			company = row.company;
			return `${group}<tr class="${row.locked ? "ppi-locked" : ""}">
				<td class="ppi-name"><div class="ppi-emp">${esc(row.employee_name || row.employee)}${row.locked ? `<span class="ppi-lock" title="${esc(__("Slip periode ini sudah disubmit"))}">${frappe.utils.icon("lock", "xs")}</span>` : ""}</div><div class="ppi-id">${esc(row.employee)}</div></td>
				${ATT.map(([key], i) => `<td class="ppi-att${i === 0 ? " ppi-first" : ""}${key !== "hadir" && att[key] ? " ppi-att-flag" : ""}">${att[key] ?? 0}</td>`).join("")}
				${ordered.map((c) => cell(row, c)).join("")}</tr>`;
		}).join("");

		const th = (c, i, list) => `<th class="ppi-amount ${c.type === "Deduction" ? "ppi-col-ded" : "ppi-col-earn"}${i === 0 ? " ppi-first" : ""}">${esc(c.name)}</th>`;
		this.$table.html(`<table class="ppi-table">
			<thead>
				<tr class="ppi-band"><th rowspan="2" class="ppi-name">${__("Karyawan")}</th>
					<th colspan="${ATT.length}" class="ppi-band-att ppi-first">${__("Presensi")}</th>
					${earnings.length ? `<th colspan="${earnings.length}" class="ppi-band-earn ppi-first">${__("Pendapatan")}</th>` : ""}
					${deductions.length ? `<th colspan="${deductions.length}" class="ppi-band-ded ppi-first">${__("Potongan")}</th>` : ""}</tr>
				<tr>${ATT.map(([, label], i) => `<th class="ppi-att${i === 0 ? " ppi-first" : ""}">${label}</th>`).join("")}
					${earnings.map(th).join("")}${deductions.map(th).join("")}</tr>
			</thead>
			<tbody>${body}</tbody>
			<tfoot><tr><td class="ppi-name">${__("Total")}</td><td colspan="${ATT.length}" class="ppi-first"></td>
				${ordered.map((c, i) => `<td class="ppi-amount ppi-total ${c.type === "Deduction" ? "ppi-col-ded" : "ppi-col-earn"}" data-total="${esc(c.name)}"></td>`).join("")}</tr></tfoot>
		</table>`);
		this.$table.find("thead tr:last th.ppi-col-earn").first().addClass("ppi-first");
		this.$table.find("thead tr:last th.ppi-col-ded").first().addClass("ppi-first");
		this.update_totals();
	}

	// shortcut: whole rupiah only; decimals are dropped while typing
	parse(text) {
		return Number(String(text || "").replace(/\D/g, "")) || 0;
	}

	fmt(value) {
		return value ? format_number(value, null, 0) : "";
	}

	update_totals() {
		const { components, rows } = this.data;
		const totals = Object.fromEntries(components.map((c) => [c.name, 0]));
		this.$table.find("input.ppi-cell").each((_, input) => { totals[input.dataset.component] += this.parse(input.value); });
		components.forEach((c) => this.$table.find(`[data-total="${CSS.escape(c.name)}"]`).text(this.fmt(totals[c.name]) || "–"));
		const { start, end } = this.data;
		const card = (label, value) => `<div class="ppi-card"><div class="ppi-card-label">${label}</div><div class="ppi-card-value">${value}</div></div>`;
		this.$summary.html(
			card(__("Periode"), `${moment(start).format("D MMM")} – ${moment(end).format("D MMM YYYY")}`) +
			card(__("Karyawan"), rows.length)
		);
	}

	edited(input) {
		const amount = this.parse(input.value);
		const caret = input.value.length - input.selectionStart;
		input.value = this.fmt(amount);
		input.setSelectionRange(Math.max(0, input.value.length - caret), Math.max(0, input.value.length - caret));
		input.classList.toggle("ppi-changed", amount !== Number(input.dataset.original || 0));
		this.update_totals();
	}

	// runs when the cell loses focus or Enter is pressed
	autosave(input) {
		const amount = this.parse(input.value);
		if (amount === Number(input.dataset.original || 0)) return;
		const month = this.args().month;
		const change = { employee: input.dataset.employee, component: input.dataset.component, amount };
		this.pending++;
		this.page.set_indicator(__("Menyimpan..."), "orange");
		// one save at a time: two quick edits of one cell must not both create an Additional Salary
		this.saving = this.saving.then(async () => {
			try {
				await frappe.call({ method: "custom_hr.api.payroll_input.save_period_input", args: { month, changes: [change] } });
				input.dataset.original = amount;
			} catch {
				input.value = this.fmt(Number(input.dataset.original || 0));
				this.update_totals();
			}
			input.classList.toggle("ppi-changed", this.parse(input.value) !== Number(input.dataset.original || 0));
			if (!--this.pending) this.page.set_indicator(__("Tersimpan"), "green");
		});
	}
}
