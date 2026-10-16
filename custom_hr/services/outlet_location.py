"""One linked native Shift Location per Outlet; no Shift Assignments created."""

from hashlib import sha256

import frappe
from frappe import _

from custom_hr.services.outlet_geofence import coordinates


def sync_outlet_location(doc, *, migrate=False):
	"""Outlet coordinate edits update the linked location, never its radius.

	Unchanged Outlet coordinates must not overwrite a later edit made directly
	in Shift Location. A new link without coordinate edits adopts that master.
	Migration/first link of an existing Outlet preserves its legacy radius;
	a brand-new Outlet uses the native zero/no-limit radius.
	"""
	old = doc.get_doc_before_save()
	linked = doc.get("shift_location")
	coordinates_changed = bool(old and any(doc.get(f) != old.get(f) for f in ("latitude", "longitude")))
	point = None
	try:
		point = coordinates(doc.get("latitude"), doc.get("longitude"))
	except ValueError:
		if coordinates_changed or (not linked and (doc.get("latitude") or doc.get("longitude"))):
			frappe.throw(_("Koordinat Outlet tidak valid. Isi Latitude -90 sampai 90 dan Longitude -180 sampai 180; gunakan pemisah desimal sesuai format angka sistem."))

	if old and old.get("shift_location") and not linked:
		frappe.throw(_("Shift Location yang sudah terhubung tidak boleh dikosongkan. Pilih lokasi pengganti agar tidak membuat duplikat."))
	if not linked and not point:
		return
	if linked:
		other = frappe.db.get_value("Outlet", {"shift_location": linked, "name": ["!=", doc.name or doc.company]}, "name")
		if other:
			frappe.throw(_("Shift Location ini sudah dipakai Outlet {0}. Gunakan lokasi tersendiri agar perubahan koordinat tidak memengaruhi Outlet lain.").format(other))
		location = frappe.get_doc("Shift Location", linked, for_update=True)
		if coordinates_changed and point:
			location.latitude, location.longitude = point
			location.save(ignore_permissions=True)
		else:
			try:
				point = coordinates(location.latitude, location.longitude)
			except ValueError:
				frappe.throw(_("Koordinat Shift Location belum valid. Perbaiki lokasi terkait atau isi ulang koordinat Outlet."))
			doc.latitude, doc.longitude = point
	else:
		name = "Outlet - " + (doc.name or doc.company)
		if len(name) > 140:
			name = name[:120] + "-" + sha256(name.encode()).hexdigest()[:16]
		# Never silently adopt an unrelated existing master with the same name.
		if frappe.db.exists("Shift Location", name):
			frappe.throw(_("Shift Location {0} sudah ada. Pilih lokasi tersebut secara eksplisit atau gunakan nama lokasi lain.").format(name))
		radius = doc.get("geofence_radius_m") if migrate or old else 0
		if radius is None:
			radius = 0
		if isinstance(radius, bool) or float(radius) < 0 or float(radius) != int(radius):
			frappe.throw(_("Radius lama Outlet tidak valid; perbaiki sebelum migrasi."))
		location = frappe.get_doc({
			"doctype": "Shift Location", "location_name": name,
			"latitude": point[0], "longitude": point[1], "checkin_radius": int(radius),
		}).insert(ignore_permissions=True)
		doc.shift_location = location.name
	doc.checkin_radius = location.checkin_radius
