"""Laporan Posisi Driver: a driver sends one photo and their GPS position a day, from 16.30 until midnight.

HR reads them to count the driver's overtime by hand. The employee, date and time come from the server, never
from the payload.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_time, getdate, now_datetime, nowdate
from hrms.api import get_current_employee

from custom_hr.api import require_page_access
from custom_hr.api.face import _save_photo_data_url
from custom_hr.services.grooming import check_image

DOCTYPE = "Laporan Posisi Driver"
DEFAULT_OPENS_AT = "16:30:00"
HISTORY_LIMIT = 30
GALLERY_PAGE = "driver-position-gallery"
CARD_FIELDS = ["name", "employee", "employee_name", "company", "report_date", "submitted_at", "photo", "latitude", "longitude", "accuracy", "maps_url", "dilihat", "catatan_hr"]


def is_driver(designation) -> bool:
	"""DRIVER and GUDANG & DRIVER JKT both report."""
	return "DRIVER" in (designation or "").upper()


def opens_at():
	"""HR sets it in Payroll Settings (tab HRM)."""
	return get_time(frappe.db.get_single_value("Payroll Settings", "driver_report_opens_at") or DEFAULT_OPENS_AT)


def is_open(now, opens) -> bool:
	return now.time() >= opens  # until midnight: the next day starts a new report


def valid_position(latitude, longitude) -> bool:
	try:
		latitude, longitude = float(latitude), float(longitude)
	except (TypeError, ValueError):
		return False
	return -90 <= latitude <= 90 and -180 <= longitude <= 180 and (latitude, longitude) != (0, 0)


def _driver():
	employee = get_current_employee()
	if not is_driver(frappe.db.get_value("Employee", employee, "designation")):
		frappe.throw(_("Laporan Posisi hanya untuk driver."), frappe.PermissionError)
	return employee


@frappe.whitelist(methods=["GET"])
def get_driver_report_status() -> dict:
	employee = _driver()
	now = now_datetime()
	today = now.date()
	history = frappe.get_all(
		DOCTYPE, filters={"employee": employee}, fields=["name", "report_date", "submitted_at", "maps_url"],
		order_by="report_date desc", page_length=HISTORY_LIMIT,
	)
	sent = next((row for row in history if row.report_date == today), None)
	opens = opens_at()
	return {
		"date": str(today),
		"opens_at": opens.strftime("%H:%M"),
		"open": is_open(now, opens),
		"submitted": bool(sent),
		"submitted_at": str(sent.submitted_at) if sent else None,
		"history": [{"name": r.name, "date": str(r.report_date), "submitted_at": str(r.submitted_at), "maps_url": r.maps_url} for r in history],
	}


@frappe.whitelist(methods=["POST"])
def submit_driver_report(photo, latitude, longitude, accuracy=None) -> dict:
	employee = _driver()
	check_image(photo)
	if not valid_position(latitude, longitude):
		frappe.throw(_("Lokasi GPS belum didapat. Nyalakan lokasi lalu coba lagi."))
	now = now_datetime()
	opens = opens_at()
	if not is_open(now, opens):
		frappe.throw(_("Laporan Posisi baru bisa dikirim mulai jam {0}.").format(opens.strftime("%H:%M")))
	if frappe.db.exists(DOCTYPE, {"employee": employee, "report_date": now.date()}):
		frappe.throw(_("Laporan Posisi hari ini sudah dikirim."))
	doc = frappe.get_doc({
		"doctype": DOCTYPE, "employee": employee, "report_date": now.date(), "submitted_at": now,
		"latitude": flt(latitude, 7), "longitude": flt(longitude, 7), "accuracy": flt(accuracy) or None,
	})
	try:
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:  # two simultaneous submissions
		frappe.throw(_("Laporan Posisi hari ini sudah dikirim."))
	url = _save_photo_data_url(photo, DOCTYPE, doc.name, f"posisi-{doc.name}")
	frappe.db.set_value(DOCTYPE, doc.name, "photo", url, update_modified=False)
	return {"name": doc.name, "submitted_at": str(now)}


@frappe.whitelist(methods=["GET"])
def get_driver_report_gallery(company=None, employee=None, dilihat=None, from_date=None, to_date=None, search=None, start=0, page_length=20) -> dict:
	"""Cards for HR, newest first. dilihat: "1" seen, "0" not yet, empty both."""
	require_page_access(GALLERY_PAGE)
	to_date = getdate(to_date) if to_date else getdate(nowdate())
	from_date = getdate(from_date) if from_date else to_date
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date"))
	filters = {"report_date": ["between", [str(from_date), str(to_date)]]}
	for fieldname, value in (("company", company), ("employee", employee)):
		if value:
			filters[fieldname] = value
	if dilihat in ("0", "1", 0, 1):
		filters["dilihat"] = cint(dilihat)
	if search:
		filters["employee_name"] = ["like", f"%{search}%"]
	start, page_length = cint(start) or 0, min(cint(page_length) or 20, 500)
	rows = frappe.get_all(DOCTYPE, filters=filters, fields=CARD_FIELDS, order_by="report_date desc, submitted_at desc", start=start, page_length=page_length)
	return {"rows": rows, "total": frappe.db.count(DOCTYPE, filters)}


@frappe.whitelist(methods=["POST"])
def review_driver_report(name, dilihat, catatan_hr=None) -> dict:
	"""Saved through the document so permissions and the change log apply."""
	require_page_access(GALLERY_PAGE)
	doc = frappe.get_doc(DOCTYPE, name)
	doc.dilihat = cint(dilihat)
	doc.catatan_hr = (catatan_hr or "").strip() or None
	doc.save()
	return {"name": doc.name, "dilihat": doc.dilihat, "catatan_hr": doc.catatan_hr}
