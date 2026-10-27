const GROOMING_COLORS = { Menunggu: "orange", Sesuai: "green", "Tidak Sesuai": "red" };

frappe.listview_settings["Grooming Check"] = {
	add_fields: ["review_status"],
	get_indicator(doc) {
		return [__(doc.review_status), GROOMING_COLORS[doc.review_status] || "gray", "review_status,=," + doc.review_status];
	},
};
