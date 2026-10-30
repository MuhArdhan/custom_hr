"""One linked native Shift Location per Outlet; no Shift Assignments created."""

from hashlib import sha256
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _

from custom_hr.services.outlet_geofence import coordinates


def radius_value(value):
	try:
		number = Decimal(str(value))
		if isinstance(value, bool) or not number.is_finite() or number < 0 or number != number.to_integral_value():
			raise ValueError
		return int(number)
	except (InvalidOperation, ValueError, TypeError):
		frappe.throw(_("Checkin Radius harus berupa bilangan bulat 0 atau lebih (meter)."))


def sync_location_radius_to_outlet(doc, method=None):
	"""Update the display copy without saving Outlet or recursing into its sync."""
	outlets = frappe.get_all("Outlet", filters={"shift_location": doc.name}, fields=["name", "checkin_radius"])
	if not outlets:
		return
	radius = radius_value(doc.checkin_radius)
	for outlet in outlets:
		if outlet.name == doc.flags.get("outlet_sync_origin") or outlet.checkin_radius == radius:
			continue
		frappe.db.set_value("Outlet", outlet.name, "checkin_radius", radius)
		frappe.clear_document_cache("Outlet", outlet.name)
		frappe.get_doc("Outlet", outlet.name).notify_update()


def sync_outlet_location(doc, *, migrate=False):
	"""Explicit Outlet coordinate/radius edits update its linked native master.

	Unchanged Outlet coordinates must not overwrite a later edit made directly
	in Shift Location. A new link without coordinate edits adopts that master.
	Migration/first link of an existing Outlet preserves its legacy radius;
	a brand-new Outlet uses the native zero/no-limit radius.
	"""
	old = doc.get_doc_before_save()
	linked = doc.get("shift_location")
	coordinates_changed = bool(old and any(doc.get(f) != old.get(f) for f in ("latitude", "longitude")))
	radius_changed = not migrate and doc.get("checkin_radius") is not None and (
		(old and old.get("shift_location") == linked and doc.get("checkin_radius") != old.get("checkin_radius"))
		or (not old and not linked and doc.get("checkin_radius") != 0)
	)
	radius = radius_value(doc.checkin_radius) if radius_changed else None
	if old and old.get("shift_location") and not linked:
		# Unlinking removes the outlet's location (check-in records GPS only); the Shift Location itself is kept.
		doc.latitude = doc.longitude = 0
		return
	point = None
	# Both coordinates empty means the outlet has no location: check-in only records GPS.
	cleared = not doc.get("latitude") and not doc.get("longitude")
	try:
		point = coordinates(doc.get("latitude"), doc.get("longitude"))
	except ValueError:
		if not cleared and (coordinates_changed or not linked):
			frappe.throw(_("Koordinat Outlet tidak valid. Isi Latitude -90 sampai 90 dan Longitude -180 sampai 180; gunakan pemisah desimal sesuai format angka sistem."))

	if not linked and not point:
		return
	if linked:
		other = frappe.db.get_value("Outlet", {"shift_location": linked, "name": ["!=", doc.name or doc.company]}, "name")
		if other:
			frappe.throw(_("Shift Location ini sudah dipakai Outlet {0}. Gunakan lokasi tersendiri agar perubahan koordinat tidak memengaruhi Outlet lain.").format(other))
		location = frappe.get_doc("Shift Location", linked, for_update=True)
		location_changed = False
		if coordinates_changed and (point or cleared):
			location.latitude, location.longitude = point or (0, 0)
			location_changed = True
		else:
			try:
				point = coordinates(location.latitude, location.longitude)
			except ValueError:
				if location.latitude or location.longitude:
					frappe.throw(_("Koordinat Shift Location belum valid. Perbaiki lokasi terkait atau isi ulang koordinat Outlet."))
				point = (0, 0)  # the linked location has no coordinates either
			doc.latitude, doc.longitude = point
		# A replacement link always adopts the selected master's settings.
		if radius_changed and old and old.get("shift_location") == linked:
			location.checkin_radius = radius
			location_changed = True
		if location_changed:
			location.flags.outlet_sync_origin = doc.name
			location.save(ignore_permissions=True)
	else:
		name = "Outlet - " + (doc.name or doc.company)
		if len(name) > 140:
			name = name[:120] + "-" + sha256(name.encode()).hexdigest()[:16]
		if frappe.db.exists("Shift Location", name):
			# This outlet's own location from an earlier link: reuse it instead of making a duplicate.
			other = frappe.db.get_value("Outlet", {"shift_location": name, "name": ["!=", doc.name or doc.company]}, "name")
			if other:
				frappe.throw(_("Shift Location {0} sudah dipakai Outlet {1}. Gunakan lokasi tersendiri.").format(name, other))
			location = frappe.get_doc("Shift Location", name, for_update=True)
			location.latitude, location.longitude = point
			if radius_changed:
				location.checkin_radius = radius
			location.flags.outlet_sync_origin = doc.name
			location.save(ignore_permissions=True)
			doc.shift_location = location.name
			doc.checkin_radius = location.checkin_radius
			return
		radius = radius if radius_changed else doc.get("geofence_radius_m") if migrate or old else 0
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
