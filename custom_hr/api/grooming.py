# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Grooming SOP photos: the employee and the date come from the server, never from the payload."""

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime, nowdate
from hrms.api import get_current_employee

from custom_hr.api import require_page_access
from custom_hr.api.face import _save_photo_data_url
from custom_hr.services.grooming import GROOMING_STEPS, STEP_TITLES, check_image

GALLERY_PAGE = "grooming-gallery"
REVIEW_STATUSES = ("Menunggu", "Sesuai", "Tidak Sesuai")
HISTORY_LIMIT = 30
CARD_FIELDS = ["name", "employee", "employee_name", "company", "outlet", "shift", "grooming_date", "submitted_at", "review_status", "review_note", "reviewed_by", "reviewed_on"]


def _checkin_today(employee, today):
	"""The employee's latest IN today: grooming is only open after checking in, and takes that shift."""
	return frappe.db.get_value(
		"Employee Checkin",
		{"employee": employee, "log_type": "IN", "time": ["between", [f"{today} 00:00:00", f"{today} 23:59:59"]]},
		["name", "shift"], order_by="time desc", as_dict=True,
	)


@frappe.whitelist(methods=["GET"])
def get_grooming_status() -> dict:
	"""Today's grooming for the logged-in employee: the steps, check-in state, and the recent history."""
	employee = get_current_employee()
	today = nowdate()
	checkin = _checkin_today(employee, today)
	history = frappe.get_all(
		"Grooming Check", filters={"employee": employee}, fields=["name", "grooming_date", "shift", "review_status", "review_note"],
		order_by="grooming_date desc", page_length=HISTORY_LIMIT,
	)
	record = frappe.db.get_value(
		"Grooming Check", {"employee": employee, "grooming_date": today}, ["name", "review_status", "review_note"], as_dict=True,
	)
	return {
		"date": today,
		"steps": [dict(step) for step in GROOMING_STEPS],
		"checked_in": bool(checkin),
		"shift": checkin.shift if checkin else None,
		"history": [
			{"name": row.name, "date": str(row.grooming_date), "shift": row.shift, "review_status": row.review_status, "review_note": row.review_note}
			for row in history
		],
		"submitted": bool(record),
		"review_status": record.review_status if record else None,
		"review_note": record.review_note if record else None,
	}


@frappe.whitelist(methods=["GET"])
def get_grooming_detail(name) -> dict:
	"""One of the logged-in employee's own groomings, with its photos."""
	employee = get_current_employee()
	record = frappe.db.get_value(
		"Grooming Check", name,
		["name", "employee", "grooming_date", "shift", "submitted_at", "review_status", "review_note", "reviewed_on"], as_dict=True,
	)
	if not record or record.employee != employee:  # a missing and a foreign record look the same
		frappe.throw(_("Grooming tidak ditemukan."), frappe.PermissionError)
	photos = frappe.get_all("Grooming Photo", filters={"parent": name, "parenttype": "Grooming Check"}, fields=["step", "photo"], order_by="idx asc")
	return {
		"name": record.name, "date": str(record.grooming_date), "shift": record.shift, "submitted_at": str(record.submitted_at or ""),
		"review_status": record.review_status, "review_note": record.review_note,
		"reviewed_on": str(record.reviewed_on) if record.reviewed_on else None,
		"photos": [{"step": item.step, "title": STEP_TITLES.get(item.step, item.step), "photo": item.photo} for item in photos],
	}


@frappe.whitelist(methods=["POST"])
def submit_grooming(photos) -> dict:
	"""Store all photos (data URLs, in step order) as one Grooming Check; once a day, final."""
	employee = get_current_employee()
	if isinstance(photos, str):
		photos = frappe.parse_json(photos)
	if not isinstance(photos, list) or len(photos) != len(GROOMING_STEPS):
		frappe.throw(_("Grooming harus berisi tepat {0} foto.").format(len(GROOMING_STEPS)))
	for data_url in photos:
		check_image(data_url)  # every photo is validated before the first write
	today = nowdate()
	checkin = _checkin_today(employee, today)
	if not checkin:
		frappe.throw(_("Lakukan check in terlebih dahulu sebelum grooming."))
	if frappe.db.exists("Grooming Check", {"employee": employee, "grooming_date": today}):
		frappe.throw(_("Grooming hari ini sudah dikirim."))
	now = now_datetime()
	doc = frappe.get_doc({
		"doctype": "Grooming Check", "employee": employee, "grooming_date": today, "submitted_at": now,
		"shift": checkin.shift, "checkin": checkin.name,
		# the real file URLs need the record's name, so the rows start with a placeholder
		"photos": [{"step": step["key"], "photo": "pending", "taken_at": now} for step in GROOMING_STEPS],
	})
	try:
		doc.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:  # two simultaneous submissions
		frappe.throw(_("Grooming hari ini sudah dikirim."))
	for row, step, data_url in zip(doc.photos, GROOMING_STEPS, photos):
		url = _save_photo_data_url(data_url, "Grooming Check", doc.name, f"grooming-{doc.name}-{step['key']}")
		frappe.db.set_value("Grooming Photo", row.name, "photo", url, update_modified=False)
	return {"name": doc.name, "review_status": "Menunggu"}


@frappe.whitelist(methods=["GET"])
def get_grooming_gallery(
	company=None, outlet=None, employee=None, review_status=None, from_date=None, to_date=None, search=None, start=0, page_length=24,
) -> dict:
	"""Cards for the SOP team: one per grooming, with its photos in step order."""
	require_page_access(GALLERY_PAGE)
	to_date = getdate(to_date) if to_date else getdate(nowdate())
	from_date = getdate(from_date) if from_date else to_date
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	filters = {"grooming_date": ["between", [str(from_date), str(to_date)]]}
	for fieldname, value in (("company", company), ("outlet", outlet), ("employee", employee)):
		if value:
			filters[fieldname] = value
	if review_status in REVIEW_STATUSES:
		filters["review_status"] = review_status
	if search:
		filters["employee_name"] = ["like", f"%{search}%"]

	start, page_length = cint(start) or 0, min(cint(page_length) or 24, 100)
	rows = frappe.get_all(
		"Grooming Check", filters=filters, fields=CARD_FIELDS, order_by="grooming_date desc, submitted_at desc",
		start=start, page_length=page_length + 1,
	)
	has_more = len(rows) > page_length
	rows = rows[:page_length]
	if not rows:
		return {"rows": [], "has_more": False}

	photos = frappe.get_all(
		"Grooming Photo", filters={"parent": ["in", [row.name for row in rows]], "parenttype": "Grooming Check"},
		fields=["parent", "step", "photo", "idx"], order_by="idx asc",
	)
	for row in rows:
		row["photos"] = [
			{"step": item.step, "title": STEP_TITLES.get(item.step, item.step), "photo": item.photo} for item in photos if item.parent == row.name
		]
	return {"rows": rows, "has_more": has_more}


@frappe.whitelist(methods=["POST"])
def review_grooming(name, review_status, review_note=None) -> dict:
	"""Judge a grooming from the gallery. Saved through the document so the reviewer stamp and permissions apply."""
	require_page_access(GALLERY_PAGE)
	if review_status not in REVIEW_STATUSES:
		frappe.throw(_("Status penilaian tidak valid."))
	doc = frappe.get_doc("Grooming Check", name)
	doc.review_status = review_status
	doc.review_note = (review_note or "").strip() or None
	doc.save()
	return {
		"name": doc.name, "review_status": doc.review_status, "review_note": doc.review_note,
		"reviewed_by": doc.reviewed_by, "reviewed_on": str(doc.reviewed_on) if doc.reviewed_on else None,
	}
