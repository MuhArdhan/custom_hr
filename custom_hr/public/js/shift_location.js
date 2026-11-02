// HRMS only draws the map from Latitude/Longitude (and redraws it on save); a marker placed on the map fills them here.
frappe.ui.form.on("Shift Location", {
	async geolocation(frm) {
		const point = marker_coordinates(frm.doc.geolocation);
		if (point && (point.latitude !== frm.doc.latitude || point.longitude !== frm.doc.longitude)) {
			await frm.set_value(point);
		}
	},
});

// The last marker on the map (the one just placed); GeoJSON stores longitude first.
function marker_coordinates(geojson) {
	let features;
	try {
		features = JSON.parse(geojson || "{}").features || [];
	} catch {
		return null;
	}
	const marker = features.filter((feature) => feature.geometry?.type === "Point").pop();
	if (!marker) return null;
	const [longitude, latitude] = marker.geometry.coordinates;
	return { latitude, longitude };
}
