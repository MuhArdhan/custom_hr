# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""T05 IN preparation/immutability. No OUT pairing or attendance creation.

Never trust instance flags or a client-supplied snapshot to decide whether a
record is locked. The source of truth for existing logs is a current DB read.
Employee row locks live until the caller commits/rolls back; no helper commits.
"""

import json
from datetime import datetime, time, timedelta

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate

from custom_hr.hrm.doctype.outlet import outlet as outlet_configuration
from custom_hr.services.outlet_shift import resolve_outlet_shift

HR_CHECKIN_ROLES = {"HR Manager", "HR User", "System Manager"}
SOURCE_FIELDS = (
	"attendance_source",
	"outlet_at_checkin",
	"shift_work_date",
	"paired_checkin",
	"checkout_deadline",
	"shift_policy_snapshot",
)
LOCKED_FIELDS = (
	"employee", "time", "log_type", *SOURCE_FIELDS,
	"shift", "shift_start", "shift_end", "shift_actual_start", "shift_actual_end",
	"offshift", "skip_auto_attendance", "overtime_type", "attendance",
)
DATETIME_FIELDS = {"time", "checkout_deadline", "shift_start", "shift_end", "shift_actual_start", "shift_actual_end"}
SESSION_FIELDS = (
	"name", "employee", "time", "attendance_source", "shift_work_date",
	"shift_start", "shift_actual_end", "checkout_deadline",
)


def is_hr_operator() -> bool:
	return frappe.session.user == "Administrator" or bool(set(frappe.get_roles()) & HR_CHECKIN_ROLES)


def _employee_record(employee: str, *, for_update: bool) -> dict:
	record = frappe.db.get_value(
		"Employee", employee, ["name", "status", "user_id", "outlet"], as_dict=True, for_update=for_update
	)
	if not record:
		frappe.throw(_("Karyawan tidak ditemukan."))
	if not is_hr_operator() and record.user_id != frappe.session.user:
		frappe.throw(_("Anda hanya boleh mencatat absen untuk karyawan yang terhubung ke akun sendiri."), frappe.PermissionError)
	return record


def _stored_record(doc) -> dict | None:
	if doc.is_new() or not doc.get("name"):
		return None
	return frappe.db.get_value(
		"Employee Checkin", doc.name, ["name", *LOCKED_FIELDS], as_dict=True, for_update=True
	)


def _canonical(field: str, value):
	if field == "shift_policy_snapshot":
		if value in (None, ""):
			return None
		return json.loads(value) if isinstance(value, str) else value
	if field in DATETIME_FIELDS:
		return get_datetime(value) if value else None
	if field == "shift_work_date":
		return getdate(value) if value else None
	if field in {"offshift", "skip_auto_attendance"}:
		return cint(value)
	return value or None


def protect_existing_checkin(doc, stored: dict) -> bool:
	"""True means an existing locked Outlet log must not run native fetch_shift."""
	locked = stored.attendance_source == "Outlet"
	fields = LOCKED_FIELDS if locked else SOURCE_FIELDS
	if locked:
		_employee_record(stored.employee, for_update=False)
	for field in fields:
		try:
			equal = _canonical(field, doc.get(field)) == _canonical(field, stored.get(field))
		except (TypeError, ValueError, OverflowError, frappe.ValidationError):
			equal = False
		if not equal:
			frappe.throw(
				_("Field {0} pada log absen tidak dapat diubah. Untuk koreksi, hubungi HR melalui Attendance Request atau koreksi Attendance yang tercatat; snapshot IN asli dipertahankan.").format(field),
				title=_("Data Absen Terkunci"),
			)
	return locked


def _reject_native_source_payload(doc):
	for field in SOURCE_FIELDS:
		if doc.get(field) not in (None, "", {}):
			frappe.throw(_("Field {0} hanya boleh ditentukan backend untuk mode outlet.").format(field))


def _relevant_ins(employee: str, timestamp: datetime, work_date, *, outlet_only: bool) -> list[dict]:
	"""Current locking reads, not an earlier repeatable-read snapshot/cache."""
	day_start = datetime.combine(getdate(work_date), time.min)
	day_end = day_start + timedelta(days=1)
	log = frappe.qb.DocType("Employee Checkin")
	same_calendar_day = (log.time >= day_start) & (log.time < day_end)
	same_shift_day = (log.shift_start >= day_start) & (log.shift_start < day_end)
	potential_open = (log.time <= timestamp) & (
		(log.checkout_deadline >= timestamp)
		| (log.shift_actual_end >= datetime.combine(timestamp.date(), time.min))
	)
	condition = (
		(log.employee == employee)
		& (log.log_type == "IN")
		& ((log.shift_work_date == getdate(work_date)) | same_calendar_day | same_shift_day | potential_open)
	)
	if outlet_only:
		condition &= log.attendance_source == "Outlet"
	return (
		frappe.qb.from_(log).select(*(log[field] for field in SESSION_FIELDS))
		.where(condition).orderby(log.time).for_update().run(as_dict=True)
	)


def _cutoff(row: dict) -> datetime:
	if row.attendance_source == "Outlet" and row.checkout_deadline:
		return get_datetime(row.checkout_deadline)
	return get_datetime(row.shift_actual_end or row.time).replace(hour=23, minute=59, second=59, microsecond=0)


def _has_out(row: dict) -> bool:
	log = frappe.qb.DocType("Employee Checkin")
	condition = (
		(log.employee == row.employee) & (log.log_type == "OUT")
		& (log.time >= get_datetime(row.time)) & (log.time <= _cutoff(row))
	)
	if row.attendance_source == "Outlet":
		condition &= log.paired_checkin == row.name
	return bool(frappe.qb.from_(log).select(log.name).where(condition).for_update().run())


def validate_new_in_session(doc, *, outlet_only: bool = False):
	"""One IN per work date and no concurrent still-open session, even for HR."""
	timestamp = get_datetime(doc.time)
	work_date = getdate(doc.get("shift_work_date") or timestamp)
	for row in _relevant_ins(doc.employee, timestamp, work_date, outlet_only=outlet_only):
		locked_date = row.shift_work_date if row.attendance_source == "Outlet" else None
		previous_date = getdate(locked_date or row.shift_start or row.time)
		if previous_date == work_date:
			frappe.throw(_("Anda sudah memiliki check-in pada tanggal kerja ini. Double shift tidak diperbolehkan."), title=_("Sudah Check-in"))
		if get_datetime(row.time) <= timestamp <= _cutoff(row) and not _has_out(row):
			frappe.throw(_("Masih ada check-in terbuka yang belum melewati batas OUT. Selesaikan sesi tersebut terlebih dahulu."))


def _has_open_outlet_session(doc) -> bool:
	timestamp = get_datetime(doc.time)
	return any(
		get_datetime(row.time) <= timestamp <= _cutoff(row) and not _has_out(row)
		for row in _relevant_ins(doc.employee, timestamp, timestamp.date(), outlet_only=True)
	)


def prepare_or_protect_checkin(doc) -> bool:
	"""Prepare IN under lock, or preserve stored snapshot; False uses native flow.

	Safe to call again from fetch_shift. Recomputing a *new* IN overwrites any
	client fields; persisted Outlet logs never re-resolve, even after mode changes.
	"""
	stored = _stored_record(doc)
	if stored:
		return protect_existing_checkin(doc, stored)
	if not doc.is_new() and doc.get("name"):
		frappe.throw(_("Log absen tidak ditemukan. Muat ulang dokumen sebelum melanjutkan."))
	# Serialize before reading either mode or session history. Locking reads of
	# Checkin below see the preceding writer's commit even under repeatable read.
	employee = _employee_record(doc.employee, for_update=True)
	if employee.status != "Active":
		frappe.throw(_("Karyawan tidak aktif."))
	configured = bool(employee.outlet) and bool(
		frappe.db.get_value("Outlet", employee.outlet, "enable_outlet_auto_shift", for_update=True)
	)
	resolution = resolve_outlet_shift(doc.employee, doc.time, for_update=True) if configured else None
	if resolution and resolution["mode"] == "Unavailable":
		frappe.throw(resolution["message"])
	uses_outlet = bool(resolution and resolution["mode_applies"])
	if doc.log_type != "IN":
		_reject_native_source_payload(doc)
		if uses_outlet or _has_open_outlet_session(doc):
			frappe.throw(_("Pencatatan OUT untuk sesi outlet belum tersedia pada tahap ini. Integrasi OUT menunggu T06."))
		return False
	if not uses_outlet:
		_reject_native_source_payload(doc)
		validate_new_in_session(doc, outlet_only=True)
		return False
	if not outlet_configuration.OUTLET_AUTO_SHIFT_READY:
		frappe.throw(_("Mode shift otomatis belum dapat digunakan sampai integrasi OUT dan attendance selesai."))
	if not resolution["matched"]:
		frappe.throw(resolution["message"], title=_("Shift Tidak Dapat Ditentukan"))
	if doc.get("attendance"):
		frappe.throw(_("Attendance tidak boleh ditautkan melalui payload check-in baru."))
	doc.time = get_datetime(resolution["evaluated_at"])
	for field, value in resolution["checkin_values"].items():
		doc.set(field, value)
	doc.paired_checkin = None
	doc.offshift = 0
	doc.skip_auto_attendance = 0
	policy = resolution["checkin_values"]["shift_policy_snapshot"]
	doc.overtime_type = policy["overtime_type"] if policy["allow_overtime"] else None
	validate_new_in_session(doc)
	if not is_hr_operator():
		# Do not honor client-supplied ignore_validate/ignore_checkin_restrictions
		# flags. before_validate still runs when Frappe skips validate().
		doc.validate_self_service_time()
		doc.validate_face_verification()
	return True


def prevent_locked_checkin_deletion(doc):
	stored = _stored_record(doc)
	if stored and stored.attendance_source == "Outlet":
		frappe.throw(_("Log shift outlet yang terkunci tidak boleh dihapus. Gunakan koreksi Attendance oleh HR dan pertahankan jejak log asli."))
