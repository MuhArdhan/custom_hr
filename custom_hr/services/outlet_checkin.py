# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Outlet IN preparation, locked OUT pairing and immutable session logs.

Never trust instance flags or a client-supplied snapshot to decide whether a
record is locked. The source of truth for existing logs is a current DB read.
Employee row locks live until the caller commits/rolls back; no helper commits.
"""

import json
from copy import deepcopy
from datetime import datetime, time, timedelta

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate

from custom_hr.hrm.doctype.outlet import outlet as outlet_configuration
from custom_hr.services.outlet_shift import (
	get_employee_attendance_mode,
	normalize_checkin_datetime,
	resolve_outlet_shift,
)

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
OUT_COPY_FIELDS = (
	"attendance_source", "outlet_at_checkin", "shift_work_date", "checkout_deadline",
	"shift_policy_snapshot", "shift", "shift_start", "shift_end", "shift_actual_start",
	"shift_actual_end", "offshift", "skip_auto_attendance", "overtime_type",
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


def _relevant_ins(employee: str, timestamp: datetime, work_date, *, outlet_only: bool, for_update: bool = True) -> list[dict]:
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
	query = (
		frappe.qb.from_(log).select(*(log[field] for field in SESSION_FIELDS))
		.where(condition).orderby(log.time)
	)
	return (query.for_update() if for_update else query).run(as_dict=True)


def _cutoff(row: dict) -> datetime:
	if row.attendance_source == "Outlet" and row.checkout_deadline:
		return get_datetime(row.checkout_deadline)
	return get_datetime(row.shift_actual_end or row.time).replace(hour=23, minute=59, second=59, microsecond=0)


def _has_out(row: dict, *, for_update: bool = True) -> bool:
	if row.attendance_source == "Outlet":
		return bool(_linked_checkout(row, for_update=for_update))
	log = frappe.qb.DocType("Employee Checkin")
	condition = (
		(log.employee == row.employee) & (log.log_type == "OUT")
		& (log.time >= get_datetime(row.time)) & (log.time <= _cutoff(row))
	)
	query = frappe.qb.from_(log).select(log.name).where(condition)
	return bool((query.for_update() if for_update else query).run())


def _linked_checkout(row: dict, *, for_update: bool = True) -> dict | None:
	"""Any stored OUT linked to this IN closes the slot, not just today's OUT."""
	log = frappe.qb.DocType("Employee Checkin")
	query = (
		frappe.qb.from_(log).select(log.name, log.time)
		.where((log.employee == row.employee) & (log.log_type == "OUT") & (log.paired_checkin == row.name))
		.limit(1)
	)
	rows = (query.for_update() if for_update else query).run(as_dict=True)
	return rows[0] if rows else None


def _latest_in_for_checkout(employee: str, *, for_update: bool = True) -> dict | None:
	"""Use persisted chronology, never a paired_checkin selected by the client."""
	log = frappe.qb.DocType("Employee Checkin")
	query = (
		frappe.qb.from_(log).select(log.name, *(log[field] for field in LOCKED_FIELDS))
		.where((log.employee == employee) & (log.log_type == "IN"))
		.orderby(log.time, log.name, order=frappe.qb.desc).limit(2)
	)
	rows = (query.for_update() if for_update else query).run(as_dict=True)
	if len(rows) > 1 and get_datetime(rows[0].time) == get_datetime(rows[1].time) and any(row.attendance_source == "Outlet" for row in rows):
		frappe.throw(_("Ada beberapa IN pada waktu yang sama. Hubungi HR untuk memeriksa riwayat sesi; sistem tidak memilih pasangan secara sembarang."))
	return rows[0] if rows else None


def _checkout_snapshot(row: dict) -> dict:
	"""Validate source consistency without reading the current outlet/shift master."""
	try:
		snapshot = _canonical("shift_policy_snapshot", row.shift_policy_snapshot)
		valid = (
			row.attendance_source == "Outlet" and row.log_type == "IN" and not row.paired_checkin
			and all(row.get(field) for field in ("time", "shift_actual_start", "shift_actual_end"))
			and isinstance(snapshot, dict) and type(snapshot.get("version")) is int
			and snapshot["version"] == 1
			and snapshot.get("employee") == row.employee
			and snapshot.get("shift") == row.shift
			and snapshot.get("outlet") == row.outlet_at_checkin
		)
		for field in ("shift_work_date", "shift_start", "shift_end", "checkout_deadline"):
			valid = valid and bool(row.get(field)) and (
				_canonical(field, snapshot.get(field)) == _canonical(field, row.get(field))
			)
		valid = valid and get_datetime(row.shift_end) > get_datetime(row.shift_start)
		valid = valid and get_datetime(row.time) <= get_datetime(row.checkout_deadline)
		valid = valid and bool(snapshot.get("checkin_start")) and get_datetime(row.shift_actual_start) == get_datetime(snapshot["checkin_start"])
		valid = valid and get_datetime(row.shift_actual_end) == get_datetime(row.checkout_deadline)
	except (TypeError, ValueError, OverflowError, frappe.ValidationError):
		valid = False
	if not valid:
		frappe.throw(_("Snapshot IN tidak lengkap, tidak konsisten, atau versinya belum didukung. Hubungi HR; OUT tidak akan memilih shift pengganti."))
	return snapshot


def _validate_outlet_self_service(doc):
	if not is_hr_operator():
		# before_validate runs even when instance validation flags are supplied.
		doc.validate_self_service_time()
		doc.validate_face_verification()


def prepare_outlet_checkout(doc, row: dict) -> bool:
	"""Employee is already locked by the caller. OUT copies only persisted IN."""
	if row.employee != doc.employee:
		frappe.throw(_("Check-in pasangan bukan milik karyawan ini."), frappe.PermissionError)
	snapshot = _checkout_snapshot(row)
	timestamp = get_datetime(doc.time)
	if timestamp < get_datetime(row.time):
		frappe.throw(_("Waktu OUT tidak boleh lebih awal daripada waktu IN."))
	if timestamp > get_datetime(row.checkout_deadline):
		frappe.throw(_("Batas check-out sesi sudah lewat. OUT sesi tersebut tetap kosong; hubungi HR untuk koreksi Attendance."), title=_("Batas OUT Terlewat"))
	if _linked_checkout(row):
		frappe.throw(_("Sesi check-in ini sudah memiliki OUT. Check-out kedua tidak diperbolehkan."), title=_("Sudah Check-out"))
	if doc.get("attendance"):
		frappe.throw(_("Attendance tidak boleh ditautkan melalui payload check-out baru."))
	for field in OUT_COPY_FIELDS:
		doc.set(field, deepcopy(row.get(field)))
	doc.shift_policy_snapshot = deepcopy(snapshot)
	doc.paired_checkin = row.name
	_validate_outlet_self_service(doc)
	return True


def validate_new_in_session(doc, *, outlet_only: bool = False, for_update: bool = True):
	"""One IN per work date and no concurrent still-open session, even for HR."""
	timestamp = get_datetime(doc.time)
	work_date = getdate(doc.get("shift_work_date") or timestamp)
	options = {} if for_update else {"for_update": False}
	for row in _relevant_ins(doc.employee, timestamp, work_date, outlet_only=outlet_only, **options):
		locked_date = row.shift_work_date if row.attendance_source == "Outlet" else None
		previous_date = getdate(locked_date or row.shift_start or row.time)
		if previous_date == work_date:
			frappe.throw(_("Anda sudah memiliki check-in pada tanggal kerja ini. Double shift tidak diperbolehkan."), title=_("Sudah Check-in"))
		if get_datetime(row.time) <= timestamp <= _cutoff(row) and not _has_out(row, **options):
			frappe.throw(_("Masih ada check-in terbuka yang belum melewati batas OUT. Selesaikan sesi tersebut terlebih dahulu."))


def prepare_or_protect_checkin(doc) -> bool:
	"""Prepare IN/OUT under lock, or preserve stored snapshot; False uses native.

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
	if doc.log_type == "OUT":
		try:
			doc.time = normalize_checkin_datetime(doc.time)
		except (TypeError, ValueError, OverflowError, KeyError):
			frappe.throw(_("Waktu absen atau timezone site tidak valid."))
		latest = _latest_in_for_checkout(doc.employee)
		if latest and latest.attendance_source == "Outlet":
			# Finish the existing session even after transfer/mode-off. Do not
			# consult the IN resolver, current outlet or current Shift Type here.
			return prepare_outlet_checkout(doc, latest)
		_reject_native_source_payload(doc)
		if latest and get_datetime(latest.time) <= get_datetime(doc.time) <= _cutoff(latest) and not _has_out(latest):
			return False  # Allow an open native IN from before mode activation.
		configured = bool(employee.outlet) and bool(
			frappe.db.get_value("Outlet", employee.outlet, "enable_outlet_auto_shift", for_update=True)
		)
		mode = get_employee_attendance_mode(doc.employee, doc.time, for_update=True) if configured else None
		if mode and mode["mode"] == "Unavailable":
			frappe.throw(mode["message"])
		if mode and mode["mode_applies"]:
			frappe.throw(_("Tidak ada IN outlet terbuka untuk check-out. Lakukan check-in terlebih dahulu."), title=_("Tidak Ada Check-in"))
		return False
	configured = bool(employee.outlet) and bool(
		frappe.db.get_value("Outlet", employee.outlet, "enable_outlet_auto_shift", for_update=True)
	)
	# The employee's dropdown choice (same-start shifts) arrives as the checkin's shift; the resolver
	# validates it against the candidates and ignores it when there is only one.
	resolution = resolve_outlet_shift(doc.employee, doc.time, for_update=True, chosen_shift=doc.get("shift") or None) if configured else None
	if resolution and resolution["mode"] == "Unavailable":
		frappe.throw(resolution["message"])
	uses_outlet = bool(resolution and resolution["mode_applies"])
	if doc.log_type != "IN":
		_reject_native_source_payload(doc)
		if uses_outlet:
			frappe.throw(_("Log Type untuk mode outlet harus IN atau OUT."))
		return False
	if not uses_outlet:
		_reject_native_source_payload(doc)
		validate_new_in_session(doc, outlet_only=True)
		return False
	if not outlet_configuration.OUTLET_AUTO_SHIFT_READY:
		frappe.throw(_("Mode shift otomatis belum dapat digunakan sampai integrasi attendance dan scheduler selesai."))
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
	_validate_outlet_self_service(doc)
	return True
