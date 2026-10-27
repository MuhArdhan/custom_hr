// The five photos side by side, in the order they were taken, for the SOP review.
const GROOMING_TITLES = {
	right_hand: "Tangan kanan",
	left_hand: "Tangan kiri",
	cap: "Topi",
	trousers: "Celana",
	footwear: "Alas kaki",
};

frappe.ui.form.on("Grooming Check", {
	refresh(frm) {
		const esc = frappe.utils.escape_html;
		const cards = (frm.doc.photos || [])
			.filter((row) => row.photo && row.photo !== "pending")
			.map((row) => {
				const title = esc(GROOMING_TITLES[row.step] || row.step);
				return `<div style="display:inline-block;vertical-align:top;width:19%;min-width:160px;margin:0 8px 12px 0">
					<a href="${esc(row.photo)}" target="_blank"><img src="${esc(row.photo)}" alt="${title}" style="width:100%;border-radius:6px;border:1px solid var(--border-color)"></a>
					<div class="text-muted small" style="margin-top:4px">${title}</div>
				</div>`;
			})
			.join("");
		frm.get_field("photos_html").$wrapper.html(cards || `<p class="text-muted">${__("No photos")}</p>`);
	},
});
