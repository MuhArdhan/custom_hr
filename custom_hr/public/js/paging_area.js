// Numbered paging under a desk gallery, built from the native list paging area
// (frappe/list/base_list.js): page-size pills on the left, ‹ 1 2 … n › on the right.
frappe.provide("custom_hr");

custom_hr.PagingArea = class PagingArea {
	// on_change(): called after the page or the page size changed; read page_index / page_length then
	constructor({ parent, page_length = 20, sizes = [20, 100, 500], on_change }) {
		this.page_index = 0;
		this.page_length = page_length;
		this.$wrapper = $(
			`<div class="list-paging-area level">
				<div class="level-left"></div>
				<div class="level-right"><div class="btn-group"></div></div>
			</div>`
		).appendTo(parent);
		this.size_buttons = new frappe.ui.TabButtons({
			label: __("Page Size"),
			options: sizes.map((value) => ({ label: String(value), value })),
			value: page_length,
			on_change: (value) => {
				this.page_length = value;
				this.page_index = 0;
				on_change();
			},
		});
		this.$wrapper.find(".level-left").append(this.size_buttons.$el);
		this.$wrapper.on("click", ".paging-page:not([disabled])", (event) => {
			this.page_index = Number(event.currentTarget.dataset.page);
			on_change();
			$(parent)[0].scrollIntoView({ block: "start" });
		});
		this.$wrapper.hide();
	}

	get start() {
		return this.page_index * this.page_length;
	}

	// 1-based page numbers to show: first, last, and two either side of the current page, gaps as null
	static page_numbers(current, count) {
		const pages = [];
		for (let page = 1; page <= count; page++) {
			if (page === 1 || page === count || Math.abs(page - current) <= 2) pages.push(page);
			else if (pages[pages.length - 1] !== null) pages.push(null);
		}
		return pages;
	}

	render(total, visible = true) {
		const count = Math.max(1, Math.ceil((total || 0) / this.page_length));
		const current = Math.min(this.page_index + 1, count);
		const button = (page, label, extra = "") =>
			`<button class="btn btn-default btn-sm paging-page ${label === String(current) ? "active" : ""}"
				data-page="${page - 1}" ${extra}>${label}</button>`;
		this.$wrapper.find(".btn-group").html(
			button(current - 1, "&lsaquo;", `aria-label="${__("Previous")}" ${current === 1 ? "disabled" : ""}`) +
				PagingArea.page_numbers(current, count)
					.map((page) => (page === null ? button(0, "…", "disabled") : button(page, String(page))))
					.join("") +
				button(current + 1, "&rsaquo;", `aria-label="${__("Next")}" ${current === count ? "disabled" : ""}`)
		);
		this.$wrapper.toggle(Boolean(visible && total));
	}

	hide() {
		this.$wrapper.hide();
	}
};
