frappe.pages["grooming-gallery"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Grooming Gallery"), single_column: true });
	frappe.grooming_gallery = new GroomingGallery(page);
};

const GROOMING_PILLS = { Menunggu: "orange", Sesuai: "green", "Tidak Sesuai": "red" };
const GROOMING_STATUSES = ["Menunggu", "Sesuai", "Tidak Sesuai"];

class GroomingGallery {
	constructor(page) {
		this.page = page;
		this.page.main.addClass("gg-page");
		this.rows = [];
		this.start = 0;
		this.page_length = 24;
		this.request_id = 0;
		this.syncing_dates = false;

		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.make_filters();
		this.$summary = $('<div class="gg-summary"></div>').appendTo(this.page.main);
		this.$grid = $('<div class="gg-grid"></div>').appendTo(this.page.main);
		this.$more = $('<div class="gg-more"></div>').appendTo(this.page.main);
		this.$grid.on("click", ".gg-card", (event) => this.open(this.rows.find((row) => row.name === event.currentTarget.dataset.name)));
		this.apply_preset("Today");
		this.refresh();
	}

	make_filters() {
		this.$filters = $('<div class="gg-filters"></div>').appendTo(this.page.main);
		this.controls = {};
		// a doc keeps set_value from firing onchange for unchanged values (preset <-> dates would ping-pong)
		const doc = {};
		const add = (fieldname, df) => {
			const $wrapper = $(`<div class="gg-filter"></div>`).appendTo(this.$filters);
			const control = frappe.ui.form.make_control({ df: { fieldname, ...df }, parent: $wrapper, doc, render_input: true });
			control.refresh();
			this.controls[fieldname] = control;
		};
		const changed = () => this.refresh();
		add("company", { label: __("Company"), fieldtype: "Link", options: "Company", placeholder: __("All Companies"), change: changed });
		add("preset", { label: __("Period"), fieldtype: "Select", options: ["Today", "Yesterday", "Last 7 Days", "Last 30 Days", "Custom"], default: "Today", change: () => this.apply_preset(this.controls.preset.get_value()) });
		add("from_date", { label: __("From Date"), fieldtype: "Date", change: () => this.dates_changed() });
		add("to_date", { label: __("To Date"), fieldtype: "Date", change: () => this.dates_changed() });
		add("review_status", { label: __("Review"), fieldtype: "Select", options: ["", ...GROOMING_STATUSES], change: changed });
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
		this.start = 0;
		await this.load(false);
	}

	async load(append) {
		const request_id = ++this.request_id;
		if (!append) this.$grid.html(`<div class="gg-empty">${__("Loading...")}</div>`);
		try {
			const { message } = await frappe.call({
				method: "custom_hr.api.grooming.get_grooming_gallery",
				type: "GET",
				args: { ...this.args(), start: this.start, page_length: this.page_length },
			});
			if (request_id !== this.request_id) return;
			this.rows = append ? this.rows.concat(message.rows) : message.rows;
			this.has_more = message.has_more;
			this.render();
		} catch {
			if (request_id === this.request_id) this.$grid.html(`<div class="gg-empty">${__("Unable to load the gallery.")}</div>`);
		}
	}

	render() {
		const esc = frappe.utils.escape_html;
		this.$summary.text(this.rows.length ? __("{0} grooming shown", [this.rows.length]) : "");
		if (!this.rows.length) {
			this.$grid.html(`<div class="gg-empty">${__("No grooming in this period.")}</div>`);
			this.$more.empty();
			return;
		}
		this.$grid.html(this.rows.map((row) => `
			<div class="gg-card" data-name="${esc(row.name)}">
				<div class="gg-card-head">
					<div>
						<div class="gg-name">${esc(row.employee_name || row.employee)}</div>
						<div class="gg-sub">${esc([row.company, row.outlet].filter(Boolean).join(" · "))}</div>
					</div>
					<span class="gg-pill gg-pill-${GROOMING_PILLS[row.review_status] || "orange"}">${esc(__(row.review_status))}</span>
				</div>
				${row.photos.length ? `<img class="gg-cover" loading="lazy" src="${esc(row.photos[0].photo)}" alt="${esc(row.photos[0].title)}">` : ""}
				<div class="gg-sub">${esc(frappe.datetime.str_to_user(row.submitted_at))}</div>
			</div>`).join(""));
		this.$more.html(this.has_more ? `<button class="btn btn-default btn-sm">${__("Load More")}</button>` : "");
		this.$more.find("button").on("click", () => { this.start = this.rows.length; this.load(true); });
	}

	open(row) {
		if (!row) return;
		const esc = frappe.utils.escape_html;
		const dialog = new frappe.ui.Dialog({
			title: `${row.employee_name || row.employee} · ${frappe.datetime.str_to_user(row.grooming_date)}`,
			size: "extra-large",
			fields: [
				{ fieldname: "photos", fieldtype: "HTML" },
				{ fieldname: "review_status", fieldtype: "Select", label: __("Review"), options: GROOMING_STATUSES.join("\n"), default: row.review_status },
				{ fieldname: "review_note", fieldtype: "Small Text", label: __("Review Note"), default: row.review_note || "" },
			],
			primary_action_label: __("Save Review"),
			primary_action: async (values) => {
				const { message } = await frappe.call({
					method: "custom_hr.api.grooming.review_grooming",
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
			<div class="gg-photos">${row.photos.map((photo) => `
				<div class="gg-photo">
					<a href="${esc(photo.photo)}" target="_blank" rel="noopener"><img src="${esc(photo.photo)}" alt="${esc(photo.title)}"></a>
					<div class="gg-photo-title">${esc(photo.title)}</div>
				</div>`).join("")}</div>
			${row.reviewed_by ? `<div class="gg-reviewed">${esc(__("Reviewed by {0}", [row.reviewed_by]))}</div>` : ""}`);
		dialog.show();
	}
}
