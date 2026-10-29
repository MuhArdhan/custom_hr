frappe.pages["leave-calendar"].on_page_load = function (wrapper) {
	wrapper.leave_calendar = new LeaveCalendar(wrapper);
};

class LeaveCalendar {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({ parent: wrapper, title: __("Working Calendar"), single_column: true });
		this.month = moment(frappe.datetime.get_today()).startOf("month");
		this.token = 0;
		this.page.main.html(`
			<div class="ac-shell">
				<div class="ac-filters"></div>
				<div class="ac-toolbar">
					<div><h3 class="ac-title"></h3></div>
					<div class="ac-navigation"><button class="btn btn-default btn-sm ac-today">${__("Today")}</button><button class="btn btn-default btn-sm ac-prev" aria-label="${__("Previous month")}">&lsaquo;</button><button class="btn btn-default btn-sm ac-next" aria-label="${__("Next month")}">&rsaquo;</button></div>
				</div>
				<div class="ac-message" role="status" aria-live="polite"></div>
				<div class="ac-legend">${this.badge_types().map(([key, label]) => `<span class="ac-${key}">${label}</span>`).join("")}</div>
				<div class="ac-scroll"><div class="ac-calendar" aria-label="${__("Monthly working calendar")}"></div></div>
			</div>
		`);
		this.filters = {};
		for (const df of [
			{ fieldname: "employee", fieldtype: "Link", options: "Employee", label: __("Employee") },
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
		return [["leave_request", __("Leave Request")], ["approved_leave", __("Leave")], ["rejected", __("Rejected")], ["cancelled", __("Cancelled")]];
	}

	// Every badge on a day: the leave statuses, then pending overtime (one count per employee).
	badge_types() {
		return [...this.leave_types().map(([key, label]) => [key, label, "leave"]), ["overtime", __("Overtime"), "overtime"]];
	}

	async request(start, end, extra = {}) {
		const response = await frappe.call({ method: "custom_hr.api.leave_calendar.get_leave_calendar", type: "GET", args: { ...this.args(), start_date: start, end_date: end, ...extra } });
		return response.message;
	}

	async load() {
		const token = ++this.token;
		const first = this.month.clone().startOf("month").day(0);
		const last = first.clone().add(41, "days");
		this.page.main.find(".ac-title").text(this.month.format("MMMM YYYY"));
		this.page.main.find(".ac-message").text(__("Loading requests..."));
		this.page.main.find(".ac-calendar").html(`<div class="ac-loading"><span class="ac-spinner" aria-hidden="true"></span>${__("Preparing working calendar...")}</div>`);
		try {
			const response = await frappe.call({ method: "custom_hr.api.leave_calendar.get_leave_counts", type: "GET", args: { ...this.args(), start_date: first.format("YYYY-MM-DD"), end_date: last.format("YYYY-MM-DD") } });
			const data = response.message;
			if (token !== this.token) return;
			this.render(first, data.counts);
			this.page.main.find(".ac-message").text(data.total ? __("{0} requests in this range.", [data.total]) : __("There are no requests you can view in this range."));
		} catch {
			if (token === this.token) {
				this.page.main.find(".ac-message").text(__("The calendar could not be loaded."));
				this.page.main.find(".ac-calendar").html(`<div class="ac-loading ac-load-error"><strong>${__("Calendar unavailable")}</strong><span>${__("Check your connection and try again.")}</span><button class="btn btn-default btn-sm ac-retry">${__("Try again")}</button></div>`);
			}
		}
	}

	render(first, counts) {
		const escape = frappe.utils.escape_html;
		let html = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(day => `<div class="ac-weekday">${__(day)}</div>`).join("");
		const today = frappe.datetime.get_today();
		for (let index = 0; index < 42; index++) {
			const day = first.clone().add(index, "days");
			const date = day.format("YYYY-MM-DD");
			const values = counts[date] || {};
			html += `<div class="ac-day ${day.month() !== this.month.month() ? "ac-outside" : ""} ${date === today ? "ac-current" : ""} ${[0, 6].includes(index % 7) ? "ac-weekend" : ""}">
				<button class="ac-day-button" data-date="${date}" aria-label="${escape(day.format("dddd, DD MMMM YYYY"))}" ${date === today ? 'aria-current="date"' : ""}><span class="ac-date-number">${day.date()}</span>${date === today ? `<small>${__("Today")}</small>` : ""}</button>`;
			for (const [status, label, kind] of this.badge_types()) {
				if (values[status]) html += `<button class="ac-badge ac-${status}" data-date="${date}" data-kind="${kind}" aria-label="${escape(label)} (${Number(values[status])})"><span class="ac-badge-label">${escape(label)}</span><span class="ac-badge-count">${Number(values[status])}</span></button>`;
			}
			html += "</div>";
		}
		this.page.main.find(".ac-calendar").html(html);
	}

	open_day(date, kind = null) {
		const dialog = new frappe.ui.Dialog({ title: __("Leave, Permission & Overtime — {0}", [frappe.datetime.str_to_user(date)]), size: "extra-large", fields: [{ fieldname: "body", fieldtype: "HTML" }] });
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
			const note = item.kind === "leave" && item.from_date !== item.to_date ? __("The decision applies to the whole date range of this request.") : "";
			frappe.confirm(__("{0} request from {1} ({2})?", [action.kind === "approve" ? __("Approve") : __("Reject"), frappe.utils.escape_html(person.employee_name), frappe.utils.escape_html(item.name)]) + " " + note, () => this.decide(dialog, item, action));
		});
		const body = dialog.fields_dict.body.$wrapper;
		body.on("click", ".ac-time", (event) => this.open_time_editor(dialog, event.currentTarget));
		// Enter or leaving the field saves; Esc puts the text back.
		body.on("focusout", ".ac-hours", (event) => this.save_time(dialog, event.currentTarget.closest(".ac-time-wrap")));
		body.on("keydown", ".ac-hours", (event) => {
			const wrap = event.currentTarget.closest(".ac-time-wrap");
			if (event.key === "Enter") { event.preventDefault(); this.save_time(dialog, wrap); }
			if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); wrap.dataset.done = "1"; this.load_day(dialog); }
		});
		dialog.show();
		this.load_day(dialog);
	}

	balance_html(item) {
		// null = leave without pay (no entitlement); undefined = server sent no balance
		if (item.leave_balance === undefined) return "";
		if (item.leave_balance === null) return `<div class="ac-subline ac-balance text-muted">${__("No entitlement (leave without pay)")}</div>`;
		const over = item.exceeds_balance ? ` · ${__("request exceeds remaining balance")}` : "";
		return `<div class="ac-subline ac-balance${item.exceeds_balance ? " ac-over" : ""}">${__("Remaining balance")}: <b>${Number(item.leave_balance)}</b> ${__("days")}${over}</div>`;
	}

	async load_day(dialog) {
		const body = dialog.fields_dict.body.$wrapper;
		const token = dialog.leave_load_token = (dialog.leave_load_token || 0) + 1;
		body.text(__("Loading requests..."));
		try {
			const data = await this.request(dialog.approval_date, dialog.approval_date, { ...dialog.approval_filters, kind: dialog.approval_kind || null });
			if (token !== dialog.leave_load_token) return;
			dialog.approval_items = data.items;
			const escape = value => frappe.utils.escape_html(String(value || ""));
			if (!data.items.length) { body.text(__("There are no requests you can view on this date.")); return; }
			let html = `<div class="ac-table-scroll"><table class="table ac-table"><thead><tr><th>${__("Employee")}</th><th>${__("Leave / Permission / Overtime")}</th><th>${__("Status")}</th><th>${__("Action")}</th></tr></thead><tbody>`;
			data.items.forEach((item, index) => {
				const person = item.employees[0];
				const [status, label] = item.kind === "overtime" ? ["overtime", __("Overtime")] : this.leave_types().find(([key]) => key === item.calendar_status) || this.leave_types()[0];
				html += `<tr><td><strong>${escape(person.employee_name)}</strong><small class="text-muted ac-subline">${escape(person.employee)}</small></td>
					<td><span class="ac-kind ac-${status}">${escape(label)}</span> ${this.details_html(item, index)} ${item.from_date !== item.to_date ? `<small class="text-muted">(${escape(item.from_date)} – ${escape(item.to_date)})</small>` : ""}
					<div class="ac-subline"><button class="btn btn-link ac-open" data-index="${index}">${escape(item.name)}</button></div>${this.balance_html(item)}${item.description ? `<div class="ac-reason">${escape(item.description)}</div>` : ""}</td>
					<td><span class="ac-stage ac-${status}">${escape(item.status)}</span></td>
					<td><div class="ac-request-actions">${item.actions.length ? item.actions.map((action, actionIndex) => `<button class="btn btn-xs ${action.kind === "approve" ? "btn-primary" : "btn-danger"} ac-decision" data-index="${index}" data-action="${actionIndex}" title="${escape(action.next_state)}">${action.kind === "approve" ? __("Approve") : __("Reject")}</button>`).join("") : `<span class="text-muted">${__("View only")}</span>`}</div></td></tr>`;
			});
			body.html(html + "</tbody></table></div>");
		} catch {
			if (token === dialog.leave_load_token) body.text(__("Failed to load requests. Close and reopen this date."));
		}
	}

	// The total hours read as plain text; for the current approver a click turns them into an input.
	// Only the total changes: the end time follows from the start on the server.
	details_html(item, index) {
		const escape = value => frappe.utils.escape_html(String(value || ""));
		if (item.kind !== "overtime" || !item.actions.length || !item.start_time || !item.end_time || item.planned_hours == null) return escape(item.details);
		const span = `${item.start_time.slice(0, 5)} – ${item.end_time.slice(0, 5)}`;
		return `${escape(span)} (<span class="ac-time-wrap" data-index="${index}"><button type="button" class="ac-time" title="${__("Click to change the total hours")}">${escape(item.planned_hours)}</button></span> ${__("hours")})`;
	}

	open_time_editor(dialog, button) {
		if (dialog.approval_busy) return;
		const wrap = button.closest(".ac-time-wrap");
		const item = dialog.approval_items[Number(wrap.dataset.index)];
		const shared = item.employee_count > 1 ? `<small class="text-muted ac-subline">${__("The new hours apply to all {0} employees on {1}.", [item.employee_count, frappe.utils.escape_html(item.name)])}</small>` : "";
		wrap.innerHTML = `<input type="number" class="ac-hours" min="0.5" max="23.5" step="0.5" value="${Number(item.planned_hours)}" aria-label="${__("Total hours")}">${shared}`;
		wrap.querySelector(".ac-hours").focus();
	}

	async save_time(dialog, wrap) {
		// done: Enter already saved (the following blur must not save again) or Esc cancelled
		if (dialog.approval_busy || !wrap || wrap.dataset.done) return;
		wrap.dataset.done = "1";
		const item = dialog.approval_items[Number(wrap.dataset.index)];
		const hours = Number(wrap.querySelector(".ac-hours")?.value);
		if (item?.kind !== "overtime" || !item.actions.length || !(hours > 0) || hours === Number(item.planned_hours)) {
			await this.load_day(dialog); // nothing to save: back to the plain text
			return;
		}
		dialog.approval_busy = true;
		try {
			await frappe.call({ method: "custom_hr.api.leave_calendar.update_overtime_hours", type: "POST", args: { name: item.name, hours, modified: item.modified } });
			frappe.show_alert({ message: __("Overtime hours updated."), indicator: "green" });
		} catch {
			frappe.show_alert({ message: __("Hours not updated. Check the error message and the latest list."), indicator: "red" });
		} finally {
			dialog.approval_busy = false;
			await Promise.allSettled([this.load_day(dialog), this.load()]);
		}
	}

	async decide(dialog, item, action) {
		if (dialog.approval_busy) return;
		if (!action || !item.actions.some(allowed => allowed.action === action.action)) return;
		dialog.approval_busy = true;
		dialog.fields_dict.body.$wrapper.find(".ac-decision").prop("disabled", true);
		try {
			await frappe.call({ method: "custom_hr.api.leave_calendar.decide_approval", type: "POST", args: { doctype: item.doctype, name: item.name, action: action.action, modified: item.modified, employee: item.employee || item.employees[0].employee } });
			frappe.show_alert({ message: __("Request processed successfully."), indicator: "green" });
		} catch {
			frappe.show_alert({ message: __("Request not processed. Check the error message and the latest list."), indicator: "red" });
		} finally {
			dialog.approval_busy = false;
			await Promise.allSettled([this.load_day(dialog), this.load()]);
		}
	}
}
