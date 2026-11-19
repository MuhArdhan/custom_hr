frappe.pages["driver-position-gallery"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Galeri Posisi Driver"), single_column: true });
	frappe.require("/assets/custom_hr/js/paging_area.js", () => {
		frappe.driver_position_gallery = new DriverPositionGallery(page);
	});
};

// Same layout as the Grooming Gallery: filters, photo cards, and a dialog with the map and HR's check.
class DriverPositionGallery {
	constructor(page) {
		this.page = page;
		this.page.main.addClass("dpg-page");
		this.rows = [];
		this.request_id = 0;
		this.syncing_dates = false;

		this.page.set_secondary_action(__("Refresh"), () => this.load(), "refresh");
		this.make_filters();
		this.$summary = $('<div class="dpg-summary"></div>').appendTo(this.page.main);
		this.$grid = $('<div class="dpg-grid"></div>').appendTo(this.page.main);
		this.paging = new custom_hr.PagingArea({ parent: this.page.main, on_change: () => this.load() });
		this.paging.$wrapper.addClass("dpg-more");
		this.$grid.on("click", ".dpg-card", (event) => this.open(this.rows.find((row) => row.name === event.currentTarget.dataset.name)));
		this.apply_preset("Today");
		this.refresh();
	}

	make_filters() {
		this.$filters = $('<div class="dpg-filters"></div>').appendTo(this.page.main);
		this.controls = {};
		const doc = {};
		const add = (fieldname, df) => {
			const $wrapper = $(`<div class="dpg-filter dpg-f-${fieldname}"></div>`).appendTo(this.$filters);
			const control = frappe.ui.form.make_control({ df: { fieldname, ...df }, parent: $wrapper, doc, render_input: true });
			control.refresh();
			this.controls[fieldname] = control;
		};
		const changed = () => this.refresh();
		add("company", { label: __("Company"), fieldtype: "Link", options: "Company", placeholder: __("All Companies"), change: changed });
		add("preset", { label: __("Period"), fieldtype: "Select", options: ["Today", "Yesterday", "Last 7 Days", "Last 30 Days", "Custom"], default: "Today", change: () => this.apply_preset(this.controls.preset.get_value()) });
		add("from_date", { label: __("From Date"), fieldtype: "Date", change: () => this.dates_changed() });
		add("to_date", { label: __("To Date"), fieldtype: "Date", change: () => this.dates_changed() });
		add("dilihat", { label: __("Status"), fieldtype: "Select", options: [{ label: __("Semua"), value: "" }, { label: __("Belum dilihat"), value: "0" }, { label: __("Sudah dilihat"), value: "1" }], change: changed });
		add("search", { label: __("Search"), fieldtype: "Data", placeholder: __("Search employee") });
		this.controls.search.$input.on("input", frappe.utils.debounce(() => this.refresh(), 450));
	}

	async apply_preset(preset) {
		const today = frappe.datetime.get_today();
		const ranges = {
			Today: [today, today],
			Yesterday: [frappe.datetime.add_days(today, -1), frappe.datetime.add_days(today, -1)],
			"Last 7 Days": [frappe.datetime.add_days(today, -6), today],
			"Last 30 Days": [frappe.datetime.add_days(today, -29), today],
		};
		if (!ranges[preset] || this.syncing_dates) return;
		// set_value fires its change handler asynchronously: keep the guard up until all three are set
		this.syncing_dates = true;
		await this.controls.preset.set_value(preset);
		await this.controls.from_date.set_value(ranges[preset][0]);
		await this.controls.to_date.set_value(ranges[preset][1]);
		this.syncing_dates = false;
		if (this.$grid) this.refresh();
	}

	async dates_changed() {
		if (this.syncing_dates) return;
		this.syncing_dates = true;
		await this.controls.preset.set_value("Custom");
		this.syncing_dates = false;
		this.refresh();
	}

	args() {
		const value = (name) => this.controls[name].get_value() || null;
		return { company: value("company"), from_date: value("from_date"), to_date: value("to_date"), dilihat: value("dilihat"), search: value("search") };
	}

	async refresh() {
		if (!this.paging) return;
		this.paging.page_index = 0;
		await this.load();
	}

	async load() {
		const request_id = ++this.request_id;
		this.$grid.html(`<div class="dpg-empty">${__("Loading...")}</div>`);
		this.paging.hide();
		try {
			const { message } = await frappe.call({
				method: "custom_hr.api.driver_report.get_driver_report_gallery",
				type: "GET",
				args: { ...this.args(), start: this.paging.start, page_length: this.paging.page_length },
			});
			if (request_id !== this.request_id) return;
			this.rows = message.rows;
			this.total = message.total;
			this.render();
		} catch {
			if (request_id === this.request_id) this.$grid.html(`<div class="dpg-empty">${__("Unable to load the gallery.")}</div>`);
		}
	}

	render() {
		const esc = frappe.utils.escape_html;
		this.$summary.text(this.rows.length ? __("{0} laporan", [this.total || this.rows.length]) : "");
		this.paging.render(this.total, this.rows.length > 0);
		if (!this.rows.length) {
			this.$grid.html(`<div class="dpg-empty">${__("Tidak ada laporan posisi di periode ini.")}</div>`);
			return;
		}
		this.$grid.html(this.rows.map((row) => `
			<div class="dpg-card" data-name="${esc(row.name)}">
				<div class="dpg-cover-wrap">
					${row.photo ? `<img class="dpg-cover" loading="lazy" src="${esc(row.photo)}" alt="${esc(row.employee_name || "")}">` : ""}
					<span class="dpg-pill ${row.dilihat ? "dpg-pill-green" : "dpg-pill-orange"}">${row.dilihat ? __("Dilihat") : __("Belum dilihat")}</span>
				</div>
				<div class="dpg-card-body">
					<div class="dpg-name">${esc(row.employee_name || row.employee)}</div>
					<div class="dpg-line dpg-muted">${esc(row.company || "")}</div>
					<div class="dpg-line">${esc(frappe.datetime.str_to_user(row.submitted_at))}</div>
					${row.accuracy ? `<div class="dpg-line dpg-muted">${__("GPS ±{0} m", [Math.round(row.accuracy)])}</div>` : ""}
				</div>
			</div>`).join(""));
	}

	open(row) {
		if (!row) return;
		const esc = frappe.utils.escape_html;
		const dialog = new frappe.ui.Dialog({
			title: `${row.employee_name || row.employee} · ${frappe.datetime.str_to_user(row.submitted_at)}`,
			size: "extra-large",
			fields: [
				{ fieldname: "detail", fieldtype: "HTML" },
				// opening a report to check it usually means it is seen; HR can untick
				{ fieldname: "dilihat", fieldtype: "Check", label: __("Sudah Dilihat"), default: 1 },
				{ fieldname: "catatan_hr", fieldtype: "Small Text", label: __("Catatan HR"), default: row.catatan_hr || "" },
			],
			primary_action_label: __("Simpan"),
			primary_action: async (values) => {
				const { message } = await frappe.call({
					method: "custom_hr.api.driver_report.review_driver_report",
					type: "POST",
					args: { name: row.name, dilihat: values.dilihat, catatan_hr: values.catatan_hr },
				});
				Object.assign(row, message);
				dialog.hide();
				frappe.show_alert({ message: __("Tersimpan"), indicator: "green" });
				this.render();
			},
			secondary_action_label: __("Open Record"),
			secondary_action: () => frappe.set_route("Form", "Laporan Posisi Driver", row.name),
		});
		const embed = `https://maps.google.com/maps?q=${encodeURIComponent(`${row.latitude},${row.longitude}`)}&z=15&output=embed`;
		dialog.fields_dict.detail.$wrapper.html(`
			<div class="dpg-detail">
				<a href="${esc(row.photo || "")}" target="_blank" rel="noopener"><img class="dpg-photo" src="${esc(row.photo || "")}" alt=""></a>
				<div class="dpg-map-col">
					<iframe class="dpg-map" src="${esc(embed)}" loading="lazy" title="${esc(__("Lokasi"))}"></iframe>
					<a class="btn btn-default btn-sm" href="${esc(row.maps_url || "")}" target="_blank" rel="noopener">${__("Buka di Google Maps")}</a>
					<div class="dpg-muted">${row.accuracy ? __("Akurasi GPS ±{0} m", [Math.round(row.accuracy)]) : ""}</div>
				</div>
			</div>`);
		dialog.show();
	}
}
