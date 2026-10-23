frappe.pages["leave-calendar"].on_page_load = function (wrapper) {
	wrapper.leave_calendar = new LeaveCalendar(wrapper);
};

class LeaveCalendar {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({ parent: wrapper, title: __("Leave Calendar"), single_column: true });
		this.month = moment(frappe.datetime.get_today()).startOf("month");
		this.token = 0;
		this.page.main.html(`
			<div class="ac-shell">
				<div class="ac-filters"></div>
				<div class="ac-toolbar">
					<div><h3 class="ac-title"></h3></div>
					<div class="ac-navigation"><button class="btn btn-default btn-sm ac-today">${__("Hari ini")}</button><button class="btn btn-default btn-sm ac-prev" aria-label="${__("Bulan sebelumnya")}">&lsaquo;</button><button class="btn btn-default btn-sm ac-next" aria-label="${__("Bulan berikutnya")}">&rsaquo;</button></div>
				</div>
				<div class="ac-message" role="status" aria-live="polite"></div>
				<div class="ac-legend">${this.leave_types().map(([key, label]) => `<span class="ac-${key}">${label}</span>`).join("")}</div>
				<div class="ac-scroll"><div class="ac-calendar" aria-label="${__("Kalender cuti bulanan")}"></div></div>
			</div>
		`);
		this.filters = {};
		for (const df of [
			{ fieldname: "employee", fieldtype: "Link", options: "Employee", label: __("Karyawan") },
			{ fieldname: "company", fieldtype: "Link", options: "Company", label: __("Company") },
		]) {
			this.filters[df.fieldname] = frappe.ui.form.make_control({ parent: this.page.main.find(".ac-filters"), df: { ...df, change: () => this.load() }, render_input: true });
		}
		this.page.set_secondary_action(__("Refresh"), () => this.load(), "refresh");
		this.page.main.on("click", ".ac-prev", () => { this.month.subtract(1, "month"); this.load(); });
		this.page.main.on("click", ".ac-next", () => { this.month.add(1, "month"); this.load(); });
		this.page.main.on("click", ".ac-today", () => { this.month = moment(frappe.datetime.get_today()).startOf("month"); this.load(); });
		this.page.main.on("click", ".ac-day-button", (event) => this.open_day(event.currentTarget.dataset.date));
		this.page.main.on("click", ".ac-badge", (event) => this.open_day(event.currentTarget.dataset.date, event.currentTarget.dataset.kind));
		this.page.main.on("click", ".ac-retry", () => this.load());
		this.load();
	}

	args() {
		return Object.fromEntries(Object.entries(this.filters).map(([key, control]) => [key, control.get_value() || null]));
	}

	leave_types() {
		return [["leave_request", __("Leave Request")], ["approved_leave", __("Leave")], ["rejected", __("Ditolak")], ["cancelled", __("Dibatalkan")]];
	}

	async request(start, end, extra = {}) {
		const response = await frappe.call({ method: "custom_hr.api.leave_calendar.get_leave_calendar", type: "GET", args: { ...this.args(), start_date: start, end_date: end, ...extra, kind: "leave" } });
		return response.message;
	}

	async load() {
		const token = ++this.token;
		const first = this.month.clone().startOf("month").day(0);
		const last = first.clone().add(41, "days");
		this.page.main.find(".ac-title").text(this.month.format("MMMM YYYY"));
		this.page.main.find(".ac-message").text(__("Memuat pengajuan..."));
		this.page.main.find(".ac-calendar").html(`<div class="ac-loading"><span class="ac-spinner" aria-hidden="true"></span>${__("Menyiapkan kalender cuti...")}</div>`);
		try {
			const data = await this.request(first.format("YYYY-MM-DD"), last.format("YYYY-MM-DD"));
			if (token !== this.token) return;
			this.render(first, data.counts);
			this.page.main.find(".ac-message").text(data.items.length ? __("{0} pengajuan cuti/izin pada rentang ini.", [data.items.length]) : __("Tidak ada pengajuan cuti/izin yang dapat Anda lihat pada rentang ini."));
		} catch {
			if (token === this.token) {
				this.page.main.find(".ac-message").text(__("Kalender belum berhasil dimuat."));
				this.page.main.find(".ac-calendar").html(`<div class="ac-loading ac-load-error"><strong>${__("Kalender tidak dapat dimuat")}</strong><span>${__("Periksa koneksi, lalu coba kembali.")}</span><button class="btn btn-default btn-sm ac-retry">${__("Coba lagi")}</button></div>`);
			}
		}
	}

	render(first, counts) {
		const escape = frappe.utils.escape_html;
		let html = ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"].map(day => `<div class="ac-weekday">${__(day)}</div>`).join("");
		const today = frappe.datetime.get_today();
		for (let index = 0; index < 42; index++) {
			const day = first.clone().add(index, "days");
			const date = day.format("YYYY-MM-DD");
			const values = counts[date] || {};
			html += `<div class="ac-day ${day.month() !== this.month.month() ? "ac-outside" : ""} ${date === today ? "ac-current" : ""} ${[0, 6].includes(index % 7) ? "ac-weekend" : ""}">
				<button class="ac-day-button" data-date="${date}" aria-label="${escape(day.format("dddd, DD MMMM YYYY"))}" ${date === today ? 'aria-current="date"' : ""}><span class="ac-date-number">${day.date()}</span>${date === today ? `<small>${__("Hari ini")}</small>` : ""}</button>`;
			for (const [status, label] of this.leave_types()) {
				if (values[status]) html += `<button class="ac-badge ac-${status}" data-date="${date}" data-kind="leave" aria-label="${escape(label)} (${Number(values[status])})"><span class="ac-badge-label">${escape(label)}</span><span class="ac-badge-count">${Number(values[status])}</span></button>`;
			}
			html += "</div>";
		}
		this.page.main.find(".ac-calendar").html(html);
	}

	open_day(date, kind = null) {
		const dialog = new frappe.ui.Dialog({ title: __("Cuti & Izin — {0}", [frappe.datetime.str_to_user(date)]), size: "extra-large", fields: [{ fieldname: "body", fieldtype: "HTML" }] });
		dialog.approval_date = date;
		dialog.approval_kind = kind;
		dialog.approval_filters = this.args();
		dialog.fields_dict.body.$wrapper.on("click", ".ac-open", (event) => {
			const item = dialog.approval_items[Number(event.currentTarget.dataset.index)];
			frappe.set_route("Form", item.doctype, item.name);
			dialog.hide();
		});
		dialog.fields_dict.body.$wrapper.on("click", ".ac-decision", (event) => {
			const button = event.currentTarget;
			const item = dialog.approval_items[Number(button.dataset.index)];
			const action = item.actions[Number(button.dataset.action)];
			const person = item.employees[0];
			const note = item.kind === "leave" && item.from_date !== item.to_date ? __("Keputusan berlaku untuk seluruh rentang tanggal cuti pengajuan ini.") : "";
			frappe.confirm(__("{0} pengajuan {1} ({2})?", [action.kind === "approve" ? __("Approve") : __("Reject"), frappe.utils.escape_html(person.employee_name), frappe.utils.escape_html(item.name)]) + " " + note, () => this.decide(dialog, item, action));
		});
		dialog.show();
		this.load_day(dialog);
	}

	async load_day(dialog) {
		const body = dialog.fields_dict.body.$wrapper;
		const token = dialog.leave_load_token = (dialog.leave_load_token || 0) + 1;
		body.text(__("Memuat pengajuan..."));
		try {
			const data = await this.request(dialog.approval_date, dialog.approval_date, { ...dialog.approval_filters, kind: "leave" });
			if (token !== dialog.leave_load_token) return;
			// Ignore stale responses from an older page/server with overtime enabled.
			data.items = data.items.filter(item => item.kind === "leave" && item.doctype === "Leave Application");
			dialog.approval_items = data.items;
			const escape = value => frappe.utils.escape_html(String(value || ""));
			if (!data.items.length) { body.text(__("Tidak ada pengajuan cuti/izin yang dapat Anda lihat pada tanggal ini.")); return; }
			let html = `<div class="ac-table-scroll"><table class="table ac-table"><thead><tr><th>${__("Karyawan")}</th><th>${__("Cuti / Izin")}</th><th>${__("Status")}</th><th>${__("Aksi")}</th></tr></thead><tbody>`;
			data.items.forEach((item, index) => {
				const person = item.employees[0];
				const [status, label] = this.leave_types().find(([key]) => key === item.calendar_status) || this.leave_types()[0];
				html += `<tr><td><strong>${escape(person.employee_name)}</strong><small class="text-muted ac-subline">${escape(person.employee)}</small></td>
					<td><span class="ac-kind ac-${status}">${escape(label)}</span> ${escape(item.details)} ${item.from_date !== item.to_date ? `<small class="text-muted">(${escape(item.from_date)} – ${escape(item.to_date)})</small>` : ""}
					<div class="ac-subline"><button class="btn btn-link ac-open" data-index="${index}">${escape(item.name)}</button><span class="ac-reason" title="${escape(item.description)}">${escape(item.description)}</span></div></td>
					<td><span class="ac-stage ac-${status}">${escape(item.status)}</span></td>
					<td><div class="ac-request-actions">${item.actions.length ? item.actions.map((action, actionIndex) => `<button class="btn btn-xs ${action.kind === "approve" ? "btn-primary" : "btn-danger"} ac-decision" data-index="${index}" data-action="${actionIndex}" title="${escape(action.next_state)}">${action.kind === "approve" ? __("Approve") : __("Reject")}</button>`).join("") : `<span class="text-muted">${__("Hanya lihat")}</span>`}</div></td></tr>`;
			});
			body.html(html + "</tbody></table></div>");
		} catch {
			if (token === dialog.leave_load_token) body.text(__("Gagal memuat pengajuan. Tutup lalu buka kembali tanggal ini."));
		}
	}

	async decide(dialog, item, action) {
		if (item.kind !== "leave" || item.doctype !== "Leave Application") {
			frappe.show_alert({ message: __("Approval lembur dinonaktifkan sementara."), indicator: "orange" });
			return;
		}
		if (dialog.approval_busy) return;
		if (!action || !item.actions.some(allowed => allowed.action === action.action)) return;
		dialog.approval_busy = true;
		dialog.fields_dict.body.$wrapper.find(".ac-decision").prop("disabled", true);
		try {
			await frappe.call({ method: "custom_hr.api.leave_calendar.decide_approval", type: "POST", args: { doctype: item.doctype, name: item.name, action: action.action, modified: item.modified, employee: item.employee || item.employees[0].employee } });
			frappe.show_alert({ message: __("Pengajuan berhasil diproses."), indicator: "green" });
		} catch {
			frappe.show_alert({ message: __("Pengajuan tidak diproses. Periksa pesan kesalahan dan daftar terbaru."), indicator: "red" });
		} finally {
			dialog.approval_busy = false;
			await Promise.allSettled([this.load_day(dialog), this.load()]);
		}
	}
}
