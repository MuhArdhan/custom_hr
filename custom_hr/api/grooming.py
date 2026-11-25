# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Grooming SOP photos: the employee and the date come from the server, never from the payload."""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate, now_datetime, nowdate
from hrms.api import get_current_employee

from custom_hr.api import require_page_access
from custom_hr.api.face import _save_photo_data_url
from custom_hr.services.grooming import GROOMING_STEPS, STEP_TITLES, check_image
from custom_hr.services.grooming_classifier import (
	classify_grooming_photos,
	get_grooming_settings,
	read_doc_photos_bytes,
)

GALLERY_PAGE = "grooming-gallery"
KUKU_GALLERY_PAGE = "grooming-kuku-gallery"
KUKU_STEPS = ("right_hand", "left_hand")
REVIEW_STATUSES = ("Menunggu", "Sesuai", "Tidak Sesuai")
HISTORY_LIMIT = 30
CARD_FIELDS = ["name", "employee", "employee_name", "company", "outlet", "shift", "grooming_date", "submitted_at", "review_status", "review_note", "reviewed_by", "reviewed_on"]
KUKU_CARD_FIELDS = ["name", "employee", "employee_name", "company", "outlet", "shift", "grooming_date", "submitted_at", "nail_review_status", "nail_review_note", "nail_reviewed_by", "nail_reviewed_on"]


def _checkin_today(employee, today):
	"""The employee's latest IN today: grooming is only open after checking in, and takes that shift."""
	return frappe.db.get_value(
		"Employee Checkin",
		{"employee": employee, "log_type": "IN", "time": ["between", [f"{today} 00:00:00", f"{today} 23:59:59"]]},
		["name", "shift"], order_by="time desc", as_dict=True,
	)


def grooming_deadline(employee, today):
	"""Grooming closes N minutes (HR Settings) after the first IN of the day, so checking in again does not
	extend it. 0 or blank: no limit."""
	minutes = cint(frappe.db.get_single_value("HR Settings", "grooming_deadline_minutes"))
	if minutes <= 0:
		return None
	first_in = frappe.db.get_value(
		"Employee Checkin",
		{"employee": employee, "log_type": "IN", "time": ["between", [f"{today} 00:00:00", f"{today} 23:59:59"]]},
		"time", order_by="time asc",
	)
	return get_datetime(first_in) + timedelta(minutes=minutes) if first_in else None


@frappe.whitelist(methods=["GET"])
def get_grooming_status() -> dict:
	"""Today's grooming for the logged-in employee: the steps, check-in state, and the recent history."""
	employee = get_current_employee()
	today = nowdate()
	checkin = _checkin_today(employee, today)
	deadline = grooming_deadline(employee, today) if checkin else None
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
		"deadline": str(deadline) if deadline else None,
		"expired": bool(deadline and now_datetime() > deadline),
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


def _apply_auto_review(doc, photos_by_step: dict[str, bytes], *, settings: dict | None = None, raise_on_error: bool = False) -> bool:
	cfg = settings if settings is not None else get_grooming_settings()
	try:
		verdict = classify_grooming_photos(photos_by_step, settings=cfg)
	except Exception:
		if raise_on_error:
			raise
		frappe.log_error(frappe.get_traceback(), "Grooming auto-review failed")
		return False
	boxes_by_step = verdict.get("boxes_by_step") or {}
	for row in doc.photos:
		encoded_boxes = frappe.as_json(boxes_by_step.get(row.step) or [])
		frappe.db.set_value("Grooming Photo", row.name, "detection_boxes", encoded_boxes, update_modified=False)
		row.detection_boxes = encoded_boxes
	doc.review_status = verdict["review_status"]
	doc.review_note = verdict["review_note"]
	doc.flags.auto_review = True
	doc.save(ignore_permissions=True)
	return True


@frappe.whitelist(methods=["POST"])
def submit_grooming(photos) -> dict:
	"""Store all photos (data URLs, in step order) as one Grooming Check; once a day, final."""
	employee = get_current_employee()
	if isinstance(photos, str):
		photos = frappe.parse_json(photos)
	if not isinstance(photos, list) or len(photos) != len(GROOMING_STEPS):
		frappe.throw(_("Grooming harus berisi tepat {0} foto.").format(len(GROOMING_STEPS)))
	decoded = [check_image(data_url) for data_url in photos]  # every photo is validated before the first write
	today = nowdate()
	checkin = _checkin_today(employee, today)
	if not checkin:
		frappe.throw(_("Lakukan check in terlebih dahulu sebelum grooming."))
	deadline = grooming_deadline(employee, today)
	if deadline and now_datetime() > deadline:
		frappe.throw(_("Batas waktu grooming sudah lewat (sampai jam {0}).").format(deadline.strftime("%H:%M")))
	if frappe.db.exists("Grooming Check", {"employee": employee, "grooming_date": today}):
		frappe.throw(_("Grooming hari ini sudah dikirim."))
	now = now_datetime()
	doc = frappe.get_doc({
		"doctype": "Grooming Check", "employee": employee, "grooming_date": today, "submitted_at": now,
		"shift": checkin.shift, "checkin": checkin.name, "review_status": "Menunggu",
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
		row.photo = url
	settings = get_grooming_settings()
	review_status, review_note = "Menunggu", None
	if settings["enable_auto_review"]:
		photos_by_step = {step["key"]: image_bytes for step, image_bytes in zip(GROOMING_STEPS, decoded)}
		if _apply_auto_review(doc, photos_by_step, settings=settings):
			review_status, review_note = doc.review_status, doc.review_note
	return {"name": doc.name, "review_status": review_status, "review_note": review_note}


def _fetch_gallery(
	*,
	page_name: str,
	status_field: str,
	card_fields: list[str],
	step_filter: tuple[str, ...] | None = None,
	include_boxes: bool = False,
	company=None,
	outlet=None,
	employee=None,
	review_status=None,
	from_date=None,
	to_date=None,
	search=None,
	start=0,
	page_length=20,
) -> dict:
	require_page_access(page_name)
	to_date = getdate(to_date) if to_date else getdate(nowdate())
	from_date = getdate(from_date) if from_date else to_date
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	filters = {"grooming_date": ["between", [str(from_date), str(to_date)]]}
	for fieldname, value in (("company", company), ("outlet", outlet), ("employee", employee)):
		if value:
			filters[fieldname] = value
	if review_status in REVIEW_STATUSES:
		filters[status_field] = review_status
	if search:
		filters["employee_name"] = ["like", f"%{search}%"]

	start, page_length = cint(start) or 0, min(cint(page_length) or 20, 500)  # the gallery's largest page size
	rows = frappe.get_all(
		"Grooming Check", filters=filters, fields=card_fields, order_by="grooming_date desc, submitted_at desc",
		start=start, page_length=page_length + 1,
	)
	has_more = len(rows) > page_length
	rows = rows[:page_length]
	total = frappe.db.count("Grooming Check", filters)  # the page numbers; same filters as the rows
	if not rows:
		return {"rows": [], "has_more": False, "total": total}

	photo_filters = {"parent": ["in", [row.name for row in rows]], "parenttype": "Grooming Check"}
	if step_filter:
		photo_filters["step"] = ["in", list(step_filter)]
	photo_fields = ["parent", "step", "photo", "idx"] + (["detection_boxes"] if include_boxes else [])
	photos = frappe.get_all("Grooming Photo", filters=photo_filters, fields=photo_fields, order_by="idx asc")
	show_boxes = include_boxes and get_grooming_settings()["enable_box"]
	for row in rows:
		row["photos"] = [
			{
				"step": item.step,
				"title": STEP_TITLES.get(item.step, item.step),
				"photo": item.photo,
				**({"boxes": _parse_boxes(item.get("detection_boxes")) if show_boxes else []} if include_boxes else {}),
			}
			for item in photos if item.parent == row.name
		]
	return {"rows": rows, "has_more": has_more, "total": total}


def _save_review(page_name: str, name: str, status_field: str, note_field: str, by_field: str, on_field: str, review_status: str, review_note=None) -> dict:
	require_page_access(page_name)
	if review_status not in REVIEW_STATUSES:
		frappe.throw(_("Status penilaian tidak valid."))
	doc = frappe.get_doc("Grooming Check", name)
	setattr(doc, status_field, review_status)
	setattr(doc, note_field, (review_note or "").strip() or None)
	doc.save()
	reviewed_on = getattr(doc, on_field)
	return {
		"name": doc.name,
		status_field: getattr(doc, status_field),
		note_field: getattr(doc, note_field),
		by_field: getattr(doc, by_field),
		on_field: str(reviewed_on) if reviewed_on else None,
	}


@frappe.whitelist(methods=["GET"])
def get_grooming_gallery(
	company=None, outlet=None, employee=None, review_status=None, from_date=None, to_date=None, search=None, start=0, page_length=20,
) -> dict:
	"""Cards for the SOP team: one per grooming, with its photos in step order."""
	return _fetch_gallery(
		page_name=GALLERY_PAGE, status_field="review_status", card_fields=CARD_FIELDS, include_boxes=True,
		company=company, outlet=outlet, employee=employee, review_status=review_status,
		from_date=from_date, to_date=to_date, search=search, start=start, page_length=page_length,
	)


@frappe.whitelist(methods=["GET"])
def get_grooming_kuku_gallery(
	company=None, outlet=None, employee=None, review_status=None, from_date=None, to_date=None, search=None, start=0, page_length=20,
) -> dict:
	"""Cards for manual hand/nail review: only the right_hand and left_hand photos per grooming."""
	return _fetch_gallery(
		page_name=KUKU_GALLERY_PAGE, status_field="nail_review_status", card_fields=KUKU_CARD_FIELDS,
		step_filter=KUKU_STEPS, include_boxes=False,
		company=company, outlet=outlet, employee=employee, review_status=review_status,
		from_date=from_date, to_date=to_date, search=search, start=start, page_length=page_length,
	)


def _parse_boxes(raw) -> list[dict]:
	if not raw:
		return []
	if isinstance(raw, list):
		return raw
	try:
		parsed = frappe.parse_json(raw)
		return parsed if isinstance(parsed, list) else []
	except Exception:
		return []


@frappe.whitelist(methods=["POST"])
def review_grooming(name, review_status, review_note=None) -> dict:
	"""Judge a grooming from the gallery. Saved through the document so the reviewer stamp and permissions apply."""
	return _save_review(GALLERY_PAGE, name, "review_status", "review_note", "reviewed_by", "reviewed_on", review_status, review_note)


@frappe.whitelist(methods=["POST"])
def review_grooming_kuku(name, review_status, review_note=None) -> dict:
	"""Manually judge the employee's hand/nail photos from Grooming Kuku Gallery."""
	return _save_review(KUKU_GALLERY_PAGE, name, "nail_review_status", "nail_review_note", "nail_reviewed_by", "nail_reviewed_on", review_status, review_note)


@frappe.whitelist(methods=["POST"])
def recheck_grooming(name) -> dict:
	"""Re-run the 5-class auto-review classifier on a saved Grooming Check using current Grooming Settings."""
	require_page_access(GALLERY_PAGE)
	doc = frappe.get_doc("Grooming Check", name)
	photos_by_step = read_doc_photos_bytes(doc)
	if not photos_by_step:
		frappe.throw(_("Foto grooming belum tersedia untuk dijalankan auto-review."))
	_apply_auto_review(doc, photos_by_step, settings=get_grooming_settings(), raise_on_error=True)
	return {
		"name": doc.name, "review_status": doc.review_status, "review_note": doc.review_note,
		"reviewed_by": doc.reviewed_by, "reviewed_on": str(doc.reviewed_on) if doc.reviewed_on else None,
	}
