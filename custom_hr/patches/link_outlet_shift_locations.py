"""Preserve existing valid coordinates/radius in a native location, once."""

import frappe

from custom_hr.services.outlet_geofence import coordinates
from custom_hr.services.outlet_location import sync_outlet_location


def execute():
	report = {"linked": [], "skipped_invalid_coordinates": [], "already_linked": []}
	for name in frappe.get_all("Outlet", pluck="name"):
		doc = frappe.get_doc("Outlet", name)
		if doc.get("shift_location"):
			report["already_linked"].append(name)
			continue  # Idempotent; never overwrite an existing native radius.
		try:
			coordinates(doc.latitude, doc.longitude)
		except ValueError:
			report["skipped_invalid_coordinates"].append(name)
			continue  # Do not invent or repair coordinates from malformed numbers.
		sync_outlet_location(doc, migrate=True)
		frappe.db.set_value("Outlet", name, {
			"shift_location": doc.shift_location, "checkin_radius": doc.checkin_radius,
		}, update_modified=False)
		frappe.clear_document_cache("Outlet", name)
		report["linked"].append(name)
	return report
