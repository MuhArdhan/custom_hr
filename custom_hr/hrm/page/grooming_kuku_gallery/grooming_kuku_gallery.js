frappe.pages["grooming-kuku-gallery"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Grooming Kuku Gallery"), single_column: true });
	frappe.require("/assets/custom_hr/js/paging_area.js", () => {
		frappe.grooming_kuku_gallery = new GroomingKukuGallery(page);
	});
};

const KUKU_PILLS = { Menunggu: "orange", Sesuai: "green", "Tidak Sesuai": "red" };
const KUKU_STATUSES = ["Menunggu", "Sesuai", "Tidak Sesuai"];

class GroomingKukuGallery {
	constructor(page) {
		this.page = page;
		this.page.main.addClass("gk-page");
		this.rows = [];
		this.request_id = 0;
		this.syncing_dates = false;

		this.page.set_secondary_action(__("Refresh"), () => this.load(), "refresh");
		this.make_filters();
		this.$summary = $('<div class="gk-summary"></div>').appendTo(this.page.main);
		this.$grid = $('<div class="gk-grid"></div>').appendTo(this.page.main);
		this.paging = new custom_hr.PagingArea({ parent: this.page.main, on_change: () => this.load() });
		this.paging.$wrapper.addClass("gk-more");
		this.$grid.on("click", ".gk-card", (event) => this.open(this.rows.find((row) => row.name === event.currentTarget.dataset.name)));
		this.apply_preset("Today");
		this.refresh();
	}

	make_filters() {
		this.$filters = $('<div class="gk-filters"></div>').appendTo(this.page.main);
		this.controls = {};
		const doc = {};
		const add = (fieldname, df) => {
			const $wrapper = $(`<div class="gk-filter gk-f-${fieldname}"></div>`).appendTo(this.$filters);
			const control = frappe.ui.form.make_control({ df: { fieldname, ...df }, parent: $wrapper, doc, render_input: true });
			control.refresh();
			this.controls[fieldname] = control;
		};
		const changed = () => this.refresh();
		add("company", { label: __("Company"), fieldtype: "Link", options: "Company", placeholder: __("All Companies"), change: changed });
		add("preset", { label: __("Period"), fieldtype: "Select", options: ["Today", "Yesterday", "Last 7 Days", "Last 30 Days", "Custom"], default: "Today", change: () => this.apply_preset(this.controls.preset.get_value()) });
		add("from_date", { label: __("From Date"), fieldtype: "Date", change: () => this.dates_changed() });
		add("to_date", { label: __("To Date"), fieldtype: "Date", change: () => this.dates_changed() });
		add("review_status", { label: __("Review Kuku"), fieldtype: "Select", options: ["", ...KUKU_STATUSES], change: changed });
		add("search", { label: __("Search"), fieldtype: "Data", placeholder: __("Search employee") });
		this.controls.search.$input.on("input", frappe.utils.debounce(() => this.refresh(), 450));
	}

	apply_preset(preset) {
		const today = frappe.datetime.get_today();
		const ranges = {
			Today: [today, today],
			Yesterday: [frappe.datetime.add_days(today, -1), frappe.datetime.add_days(today, -1)],
			"Last 7 Days": [frappe.datetime.add_days(today, -6), today],
			"Last 30 Days": [frappe.datetime.add_days(today, -29), today],
		};
		if (!ranges[preset]) return;
		this.syncing_dates = true;
		this.controls.preset.set_value(preset);
		this.controls.from_date.set_value(ranges[preset][0]);
		this.controls.to_date.set_value(ranges[preset][1]);
		this.syncing_dates = false;
		if (this.rows !== undefined && this.$grid) this.refresh();
	}

	dates_changed() {
		if (this.syncing_dates) return;
		this.syncing_dates = true;
		this.controls.preset.set_value("Custom");
		this.syncing_dates = false;
		this.refresh();
	}

	args() {
		const value = (name) => this.controls[name].get_value() || null;
		return {
			company: value("company"),
			from_date: value("from_date"),
			to_date: value("to_date"),
			review_status: value("review_status"),
			search: value("search"),
		};
	}

	async refresh() {
		if (!this.paging) return;
		this.paging.page_index = 0;
		await this.load();
	}

	async load() {
		const request_id = ++this.request_id;
		this.$grid.html(`<div class="gk-empty">${__("Loading...")}</div>`);
		this.paging.hide();
		try {
			const { message } = await frappe.call({
				method: "custom_hr.api.grooming.get_grooming_kuku_gallery",
				type: "GET",
				args: { ...this.args(), start: this.paging.start, page_length: this.paging.page_length },
			});
			if (request_id !== this.request_id) return;
			this.rows = message.rows;
			this.total = message.total;
			this.render();
		} catch {
			if (request_id === this.request_id) this.$grid.html(`<div class="gk-empty">${__("Unable to load the gallery.")}</div>`);
		}
	}

	render() {
		const esc = frappe.utils.escape_html;
		this.$summary.text(this.rows.length ? __("{0} grooming", [this.total || this.rows.length]) : "");
		this.paging.render(this.total, this.rows.length > 0);
		if (!this.rows.length) {
			this.$grid.html(`<div class="gk-empty">${__("No grooming in this period.")}</div>`);
			return;
		}
		this.$grid.html(this.rows.map((row) => {
			const status = row.nail_review_status || "Menunggu";
			const thumbs = (row.photos || []).slice(0, 2).map((p) => `<img class="gk-cover" loading="lazy" src="${esc(p.photo)}" alt="${esc(p.title)}">`).join("");
			return `
			<div class="gk-card" data-name="${esc(row.name)}">
				<div class="gk-cover-wrap">
					<div class="gk-cover-pair">${thumbs}</div>
					<span class="gk-pill gk-pill-${KUKU_PILLS[status] || "orange"}">${esc(__(status))}</span>
				</div>
				<div class="gk-card-body">
					<div class="gk-name">${esc(row.employee_name || row.employee)}</div>
					<div class="gk-line gk-muted">${esc([...new Set([row.company, row.outlet].filter(Boolean))].join(" · "))}</div>
					${row.shift ? `<div class="gk-line">${esc(row.shift)}</div>` : ""}
					<div class="gk-line gk-muted">${esc(frappe.datetime.str_to_user(row.submitted_at))}</div>
				</div>
			</div>`;
		}).join(""));
	}

	open(row) {
		if (!row) return;
		const esc = frappe.utils.escape_html;
		const status = row.nail_review_status || "Menunggu";
		const dialog = new frappe.ui.Dialog({
			title: `${row.employee_name || row.employee} · ${frappe.datetime.str_to_user(row.grooming_date)}${row.shift ? " · " + row.shift : ""}`,
			size: "extra-large",
			fields: [
				{ fieldname: "photos", fieldtype: "HTML" },
				{ fieldname: "review_status", fieldtype: "Select", label: __("Review Kuku"), options: KUKU_STATUSES.join("\n"), default: status },
				{ fieldname: "review_note", fieldtype: "Small Text", label: __("Catatan Kuku"), default: row.nail_review_note || "" },
			],
			primary_action_label: __("Save Review"),
			primary_action: async (values) => {
				const { message } = await frappe.call({
					method: "custom_hr.api.grooming.review_grooming_kuku",
					type: "POST",
					args: { name: row.name, review_status: values.review_status, review_note: values.review_note },
				});
				Object.assign(row, message);
				dialog.hide();
				frappe.show_alert({ message: __("Review saved"), indicator: "green" });
				this.render();
			},
			secondary_action_label: __("Open Record"),
			secondary_action: () => frappe.set_route("Form", "Grooming Check", row.name),
		});
		dialog.fields_dict.photos.$wrapper.html(`
			<div class="gk-photos">${(row.photos || []).map((photo) => `
				<div class="gk-photo">
					<a href="${esc(photo.photo)}" target="_blank" rel="noopener"><img src="${esc(photo.photo)}" alt="${esc(photo.title)}"></a>
					<div class="gk-photo-title">${esc(photo.title)}</div>
				</div>`).join("")}</div>
			${row.nail_reviewed_by ? `<div class="gk-reviewed">${esc(__("Reviewed by {0}", [row.nail_reviewed_by]))}</div>` : ""}`);
		dialog.show();
	}
}
