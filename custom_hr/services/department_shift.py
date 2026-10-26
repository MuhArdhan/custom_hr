"""Department auto shift: IN-time shift detection for non-outlet employees, configured per Department.

Reuses the outlet window logic; the shift is written onto the Employee Checkin so the native
Shift Type auto attendance does the rest.
"""

from datetime import date, datetime, time

import frappe
from frappe import _
from frappe.utils import cint, get_system_timezone, now_datetime
from hrms.hr.doctype.shift_assignment.shift_assignment import get_employee_shift

from custom_hr.hrm.doctype.outlet.outlet import validate_non_negative_number, validate_shift_rows
from custom_hr.services.outlet_shift import (
	SHIFT_FIELDS,
	ShiftConfigurationError,
	_clock,
	_local_datetime,
	_number,
	applies_on,
	pick_window,
	shift_windows,
)

SOURCE = "Department"
SHIFT_FIELDS_ON_CHECKIN = ("attendance_source", "shift", "shift_start", "shift_end", "shift_actual_start", "shift_actual_end")
SETTINGS = ("enable_auto_shift", "auto_shift_transition_minutes", "auto_shift_allow_unscheduled_days", "auto_shift_effective_from")


def validate_department(doc, method=None) -> None:
	"""Department validate: check the shift table, and when enabled require an active shift and stamp the first activation."""
	rows = doc.get("auto_shifts") or []
	validate_shift_rows(rows)
	if not cint(doc.get("enable_auto_shift")):
		return
	transition = validate_non_negative_number(doc.get("auto_shift_transition_minutes"), _("Jeda Peralihan IN"), integer=True)
	if transition >= 1440:
		frappe.throw(_("Jeda Peralihan IN harus kurang dari 1440 menit (satu hari)."))
	if not any(cint(row.get("enabled")) for row in rows):
		frappe.throw(_("Shift otomatis membutuhkan minimal satu shift aktif."))
	if not doc.get("auto_shift_effective_from"):
		doc.auto_shift_effective_from = now_datetime()  # earlier logs keep the native path


def day_has_shift(rows, day: date) -> bool:
	"""True when an enabled row applies on that calendar day."""
	return any(row.get("enabled") and applies_on(row, day) for row in rows)


def resolve_department_shift(employee: str, timestamp=None, chosen_shift: str | None = None) -> dict:
	"""Detect the shift for an IN from the employee's Department table; expected failures are returned, not thrown."""
	result = {
		"applies": False, "matched": False, "code": "not_applicable", "message": "",
		"choices": [], "candidates": [], "unscheduled_day": False, "checkin_values": None,
	}
	timezone = get_system_timezone()
	try:
		local_time = _local_datetime(timestamp, timezone)
	except (ValueError, TypeError, OverflowError, KeyError):
		result.update(code="invalid_timestamp", message=_("Waktu absen atau timezone site tidak valid."))
		return result
	record = frappe.db.get_value("Employee", employee, ["status", "department"], as_dict=True)
	if not record or record.status != "Active" or not record.department:
		return result
	department = frappe.db.get_value("Department", record.department, list(SETTINGS), as_dict=True)
	if not department or not cint(department.enable_auto_shift) or not department.auto_shift_effective_from:
		return result
	try:
		if local_time < _local_datetime(department.auto_shift_effective_from, timezone):
			result.update(code="not_effective_yet", message=_("Shift otomatis Department belum berlaku pada waktu absen ini."))
			return result
	except (ValueError, TypeError, OverflowError, KeyError):
		result.update(applies=True, code="invalid_configuration", message=_("Waktu mulai shift otomatis Department tidak valid."))
		return result
	result["applies"] = True
	rows = [
		frappe._dict(row) for row in frappe.get_all(
			"Outlet Shift", filters={"parent": record.department, "parenttype": "Department", "enabled": 1},
			fields=["shift_type", "enabled", "days"], order_by="idx",
		)
	]
	try:
		names = sorted({row.shift_type for row in rows})
		if not names:
			raise ShiftConfigurationError(_("Department belum memiliki daftar shift aktif."))
		shifts = frappe.get_all("Shift Type", filters={"name": ["in", names]}, fields=list(SHIFT_FIELDS))
		if {shift.name for shift in shifts} != set(names):
			raise ShiftConfigurationError(_("Salah satu Shift Type aktif Department tidak ditemukan."))
		for shift in shifts:
			_clock(shift.start_time, shift.name)
		transition = int(_number(department.auto_shift_transition_minutes, _("Jeda Peralihan IN"), integer=True))
		windows = shift_windows(rows, shifts, local_time, transition)
	except ShiftConfigurationError as exc:
		result.update(code="invalid_configuration", message=str(exc))
		return result
	except OverflowError:
		result.update(code="invalid_configuration", message=_("Tanggal kejadian shift berada di luar rentang yang didukung."))
		return result
	selected, outcome = pick_window(
		windows, local_time, chosen_shift,
		no_match_message=_("Tidak ada shift yang menerima IN pada waktu ini. Periksa jadwal atau hubungi HR."),
	)
	result.update(candidates=outcome["candidates"], choices=outcome["choices"], code=outcome["code"], message=outcome["message"])
	if selected is None:
		if outcome["code"] == "outside_checkin_window" and cint(department.auto_shift_allow_unscheduled_days) and not day_has_shift(rows, local_time.date()):
			result.update(code="unscheduled_day", unscheduled_day=True)
		return result
	deadline = datetime.combine(selected.shift_end.date(), time(23, 59, 59))
	result.update(matched=True, message=_("Shift Department berhasil ditentukan."), checkin_values={
		"attendance_source": SOURCE,
		"shift": selected.shift,
		"shift_start": str(selected.shift_start),
		"shift_end": str(selected.shift_end),
		"shift_actual_start": str(selected.checkin_start),
		"shift_actual_end": str(deadline),
	})
	return result


def _open_department_in(doc):
	"""The employee's latest IN at or before this OUT when it came from Department mode and has no OUT yet."""
	latest = frappe.db.get_value(
		"Employee Checkin", {"employee": doc.employee, "log_type": "IN", "time": ["<=", doc.time]},
		["name", "time", *SHIFT_FIELDS_ON_CHECKIN], order_by="time desc", as_dict=True,
	)
	if not latest or latest.attendance_source != SOURCE:
		return None
	if frappe.db.exists("Employee Checkin", {"employee": doc.employee, "log_type": "OUT", "time": ["between", [latest.time, doc.time]]}):
		return None
	return latest


def apply_department_shift(doc) -> bool:
	"""Employee Checkin fetch_shift hook: True when the checkin was prepared here, False to fall through to native."""
	if not doc.is_new():
		return doc.get("attendance_source") == SOURCE  # a saved log keeps the shift it got
	if doc.log_type == "OUT":
		latest = _open_department_in(doc)  # an OUT never re-resolves: it takes the open IN's shift
		if not latest:
			return False
		doc.update({field: latest[field] for field in SHIFT_FIELDS_ON_CHECKIN})
		doc.offshift = 0
		return True
	if get_employee_shift(doc.employee, doc.time, False):
		return False  # an explicit Shift Assignment wins
	resolution = resolve_department_shift(doc.employee, doc.time, chosen_shift=doc.get("shift") or None)
	if not resolution["applies"]:
		return False
	if resolution["matched"]:
		doc.update(resolution["checkin_values"])
		doc.offshift = 0
		return True
	if resolution["unscheduled_day"]:
		return False  # saved as native off-shift
	frappe.throw(resolution["message"], title=_("Shift Tidak Dapat Ditentukan"))
