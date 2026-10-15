# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Outlet geofence for new logs; no assignment lookup or client-owned context.

The controller prepares/protects the session before calling this validator.
OUT uses its persisted IN's outlet, but coordinates/radius are current master
configuration read under lock, not additional locked shift-snapshot fields.
"""

from math import isfinite

import frappe
from frappe import _
from frappe.utils import cint, flt

from hrms.hr.doctype.employee_checkin.employee_checkin import CheckinRadiusExceededError
from hrms.hr.utils import get_distance_between_coordinates


def coordinates(latitude, longitude):
	"""Reject silent Float coercion; zero on one axis is a valid coordinate.

	Frappe Float defaults cannot distinguish absent GPS/config from (0, 0),
	so that pair is reserved as unconfigured rather than a usable outlet point.
	"""
	if any(value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()) for value in (latitude, longitude)):
		raise ValueError("missing coordinates")
	try:
		lat, lon = float(latitude), float(longitude)
	except (ValueError, TypeError, OverflowError):
		raise ValueError("invalid coordinates") from None
	if not isfinite(lat) or not isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180 or (lat == 0 and lon == 0):
		raise ValueError("invalid or unconfigured coordinates")
	return lat, lon


def validate_configuration(outlet):
	"""Validate master coordinates/radius independently of a device position."""
	try:
		lat, lon = coordinates(outlet.latitude, outlet.longitude)
		if isinstance(outlet.geofence_radius_m, bool):
			raise ValueError("invalid radius")
		radius = float(outlet.geofence_radius_m)
		if not isfinite(radius) or radius <= 0:
			raise ValueError("invalid radius")
	except (ValueError, TypeError, OverflowError):
		frappe.throw(
			_("Konfigurasi lokasi Outlet {0} belum lengkap atau tidak valid. HR perlu mengisi Latitude, Longitude, dan Radius Geofence yang lebih besar dari 0.").format(outlet.name),
			title=_("Konfigurasi Geofence Outlet"),
		)
	return lat, lon, radius


def read_outlet_geofence(outlet_name):
	outlet = frappe.db.get_value(
		"Outlet", outlet_name, ["name", "latitude", "longitude", "geofence_radius_m"],
		as_dict=True, for_update=True,
	) if outlet_name else None
	if not outlet:
		frappe.throw(_("Outlet asal sesi tidak ditemukan. Hubungi HR untuk memeriksa konfigurasi lokasi; sistem tidak memakai lokasi shift pengganti."))
	validate_configuration(outlet)
	return outlet


def check_position(outlet, latitude, longitude):
	"""Pure radius check in meters. Exact boundary is inclusive, no extra buffer."""
	lat, lon, radius = validate_configuration(outlet)
	try:
		gps_lat, gps_lon = coordinates(latitude, longitude)
	except ValueError:
		frappe.throw(_("GPS tidak tersedia atau koordinat tidak valid. Aktifkan izin lokasi dan kirim Latitude serta Longitude yang lengkap."), title=_("Lokasi Diperlukan"))
	try:
		distance = get_distance_between_coordinates(lat, lon, gps_lat, gps_lon)
	except (ValueError, OverflowError):
		frappe.throw(_("Jarak GPS tidak dapat dihitung. Periksa koordinat lokasi atau hubungi HR."))
	if not isfinite(distance) or distance > radius:
		frappe.throw(
			_("Anda harus berada dalam radius {0} meter dari Outlet {1} untuk mencatat IN atau OUT.").format(radius, outlet.name),
			exc=CheckinRadiusExceededError,
		)
	return distance


def validate_outlet_geofence(doc):
	"""True means outlet handling, including disabled geolocation/old logs."""
	if doc.get("attendance_source") != "Outlet":
		return False
	# Existing logs are historical evidence, not a new punch to re-evaluate
	# against today's location master or the current device's coordinates.
	if (doc.get("name") and not doc.is_new()) or not cint(frappe.db.get_single_value("HR Settings", "allow_geolocation_tracking")):
		return True
	outlet = read_outlet_geofence(doc.get("outlet_at_checkin"))
	# Validate before Frappe can coerce invalid strings to zero, and evaluate
	# the same field precision that the Employee Checkin will actually store.
	try:
		lat, lon = coordinates(doc.get("latitude"), doc.get("longitude"))
	except ValueError:
		lat, lon = doc.get("latitude"), doc.get("longitude")
	else:
		lat, lon = flt(lat, doc.precision("latitude")), flt(lon, doc.precision("longitude"))
	check_position(outlet, lat, lon)
	doc.latitude, doc.longitude = lat, lon
	return True
