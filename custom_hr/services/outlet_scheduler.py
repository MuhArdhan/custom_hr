# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Recover real Outlet sessions; missing presences never imply auto-Absent.

No API exposure, commits, native shift sync or invented log timestamps. The
modified-time bounds deliberately avoid inferring historical outlet membership
or schedules for dates for which this installation has no temporal ledger.
"""

from datetime import datetime, time, timedelta
from hashlib import sha256

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate

from custom_hr.hrm.doctype.outlet import outlet as configuration
from custom_hr.services.outlet_attendance import (
	_approved_leaves,
	_attendance_for_date,
	_holiday_state,
)
from custom_hr.services.outlet_checkin import _linked_checkout
from custom_hr.services.outlet_geofence import read_outlet_geofence
from custom_hr.services.outlet_shift import normalize_checkin_datetime, resolve_outlet_shift


def _ceil_day(value):
	stamp = get_datetime(value)
	return stamp.date() + timedelta(days=int(stamp.time() != time.min))


def _stable_start(employee, outlet):
	return max(
		_ceil_day(outlet.outlet_auto_shift_effective_from), _ceil_day(outlet.modified),
		_ceil_day(employee.modified), getdate(employee.date_of_joining or employee.creation),
	)


def native_absence_is_managed(employee, work_date):
	"""Fail closed for dates carrying outlet provenance, even after mode-off.

	An effective-from retained on an outlet is a conservative native-absence
	boundary through its last modification date when disabled. Later native
	dates work normally; mode toggle history cannot be reconstructed exactly.
	Native logs themselves are still processed normally, including preactivation.
	"""
	day = getdate(work_date)
	outlet = frappe.db.get_value("Employee", employee, "outlet", for_update=True)
	if frappe.db.get_value("Employee Checkin", {"employee": employee, "attendance_source": "Outlet", "shift_work_date": day}, "name", for_update=True):
		return True
	if any(row.attendance_source == "Outlet" for row in _day_logs(employee, day)):
		# Also quarantine orphan/imported outlet logs whose work-date metadata
		# is missing. Their blank IN/OUT cannot justify native auto-Absent.
		return True
	if frappe.db.get_value("Attendance", {"employee": employee, "attendance_source": "Outlet", "attendance_date": day}, "name", for_update=True):
		return True
	if not outlet:
		return False
	settings = frappe.db.get_value(
		"Outlet", outlet, ["outlet_auto_shift_effective_from", "enable_outlet_auto_shift", "modified"],
		as_dict=True, for_update=True,
	)
	if not settings or not settings.outlet_auto_shift_effective_from:
		return False
	return day >= getdate(settings.outlet_auto_shift_effective_from) and (
		bool(settings.enable_outlet_auto_shift) or day <= getdate(settings.modified)
	)


def _enqueue_session(entry):
	checkout = _linked_checkout(entry, for_update=False)
	missing = checkout is None
	if missing and (not entry.checkout_deadline or normalize_checkin_datetime() <= get_datetime(entry.checkout_deadline)):
		return False
	key = sha256(f"{entry.name}:{checkout.name if checkout else 'missing'}".encode()).hexdigest()
	frappe.enqueue(
		"custom_hr.services.outlet_attendance.process_outlet_attendance",
		queue="short", enqueue_after_commit=True, deduplicate=True, job_id=f"outlet-session-{key}",
		source_checkin=entry.name, source_checkout=checkout.name if checkout else None,
		finalize_missing=missing,
	)
	return True


def recover_outlet_sessions():
	"""Keyset-paged discovery. No dependency on current mode/outlet/readiness."""
	entry = frappe.qb.DocType("Employee Checkin")
	out = frappe.qb.DocType("Employee Checkin").as_("paired_out")
	cursor = ""
	batch_size = max(cint(frappe.conf.get("outlet_scheduler_batch_size", 200)), 1)
	queued = 0
	while True:
		rows = (
			frappe.qb.from_(entry).left_join(out).on(out.paired_checkin == entry.name)
			.select(entry.name, entry.employee, entry.checkout_deadline).distinct()
			.where(
				(entry.attendance_source == "Outlet") & (entry.log_type == "IN")
				& (entry.skip_auto_attendance == 0) & (entry.offshift == 0) & (entry.name > cursor)
				& (entry.attendance.isnull() | (entry.attendance == "")
					| ((out.name.isnotnull()) & (out.attendance.isnull() | (out.attendance == ""))))
			).orderby(entry.name).limit(batch_size).run(as_dict=True)
		)
		if not rows:
			break
		for row in rows:
			try:
				if not row.checkout_deadline:
					raise ValueError("Missing checkout_deadline on outlet IN")
				queued += int(_enqueue_session(row))
			except (ValueError, TypeError, frappe.ValidationError):
				frappe.log_error(
					title="Outlet session recovery discovery failed", message=f"IN: {row.name}\n{frappe.get_traceback()}",
					reference_doctype="Employee Checkin", reference_name=row.name, defer_insert=True,
				)
		cursor = rows[-1].name
	return queued


def _day_logs(employee, work_date):
	start = datetime.combine(getdate(work_date), time.min)
	end = start + timedelta(days=1)
	log = frappe.qb.DocType("Employee Checkin")
	unknown_work_date = log.shift_work_date.isnull()
	unknown_shift = log.shift_start.isnull()
	return (
		frappe.qb.from_(log).select(log.name, log.log_type, log.attendance_source)
		.where(
			(log.employee == employee)
			& ((log.shift_work_date == getdate(work_date)) | (unknown_work_date & (
				((log.shift_start >= start) & (log.shift_start < end))
				| (unknown_shift & (log.time >= start) & (log.time < end))
			)))
		).orderby(log.name).for_update().run(as_dict=True)
	)


def _day_context(employee, work_date):
	day = getdate(work_date)
	record = frappe.db.get_value(
		"Employee", employee, ["name", "status", "outlet", "company", "modified", "creation", "date_of_joining", "relieving_date"],
		as_dict=True, for_update=True,
	)
	if not record or record.status != "Active" or not record.outlet or not configuration.OUTLET_AUTO_SHIFT_READY:
		return None, "not_active_or_ready"
	outlet = frappe.db.get_value(
		"Outlet", record.outlet,
		["name", "is_active", "enable_outlet_auto_shift", "outlet_auto_shift_effective_from", "modified", "holiday_list"],
		as_dict=True, for_update=True,
	)
	if not outlet or not outlet.enable_outlet_auto_shift or not outlet.outlet_auto_shift_effective_from:
		return None, "mode_disabled"
	if not outlet.is_active or not record.company:
		frappe.throw(_("Outlet harus aktif dan Company karyawan harus terisi untuk evaluasi Absent."))
	if cint(frappe.db.get_single_value("HR Settings", "allow_geolocation_tracking")):
		# Broken location configuration must not both reject every punch and
		# then turn the resulting lack of logs into automatic Absent.
		read_outlet_geofence(record.outlet)
	if day < _stable_start(record, outlet) or (record.relieving_date and day > getdate(record.relieving_date)):
		return None, "before_stable_activation_or_employment"
	resolution = resolve_outlet_shift(employee, datetime.combine(day, time.min), for_update=True)
	windows = [row for row in resolution["windows"] if getdate(row["shift_work_date"]) == day]
	if resolution["mode"] != "Outlet" or not windows:
		frappe.throw(resolution["message"] or _("Jadwal outlet untuk evaluasi Absent tidak tersedia."))
	shift = frappe.qb.DocType("Shift Type")
	shift_versions = (
		frappe.qb.from_(shift).select(shift.name, shift.modified)
		.where(shift.name.isin(sorted({row["shift"] for row in windows})))
		.orderby(shift.name).for_update().run(as_dict=True)
	)
	if any(day < _ceil_day(row.modified) for row in shift_versions):
		return None, "before_stable_shift_configuration"
	deadline = max(datetime.combine(get_datetime(row["shift_end"]).date(), time(23, 59, 59)) for row in windows)
	if normalize_checkin_datetime() <= deadline:
		return None, "day_still_open"
	return frappe._dict(employee=record, outlet=outlet, deadline=deadline), None


def _process_day(employee, work_date):
	# Compatibility for already queued jobs: no calendar/roster can infer
	# absence when work days are decided by management, not a fixed schedule.
	return {"status": "skipped", "reason": "no_log_absence_disabled"}


def process_outlet_day(employee: str, work_date):
	user = frappe.session.user
	frappe.set_user("Administrator")
	frappe.db.savepoint("outlet_absence_day")
	try:
		return _process_day(employee, work_date)
	except Exception:
		traceback = frappe.get_traceback()
		try:
			frappe.db.rollback(save_point="outlet_absence_day")
		except Exception:
			traceback += "\nSavepoint rollback failed:\n" + frappe.get_traceback()
		frappe.log_error(
			title="Outlet absence evaluation failed", message=f"Employee: {employee}\nWork date: {work_date}\n{traceback}",
			reference_doctype="Employee", reference_name=employee, defer_insert=True,
		)
		raise
	finally:
		frappe.set_user(user)


def _settled_dates(employee, start, end):
	"""Advisory pruning only; the date worker always rechecks under lock."""
	rows = frappe.get_all(
		"Attendance", filters={"employee": employee, "attendance_date": ["between", [start, end]]},
		fields=["attendance_date", "docstatus", "status", "modify_half_day_status", "attendance_request", "source_checkin", "leave_application"],
	)
	groups = {}
	for row in rows:
		if cint(row.docstatus) == 2 and row.leave_application:
			continue  # cancelled together with its leave; the day still needs its outlet session
		groups.setdefault(getdate(row.attendance_date), []).append(row)
	return {
		day for day, records in groups.items() if not any(
			cint(row.docstatus) == 1 and row.status == "Half Day" and cint(row.modify_half_day_status)
			and not row.attendance_request and not row.source_checkin for row in records
		)
	}


def finalize_outlet_days(employee: str):
	"""Retained as a safe no-op for legacy queued employee/day scan jobs."""
	return {"status": "skipped", "reason": "no_log_absence_disabled"}


def run_outlet_attendance_scheduler():
	return recover_outlet_sessions()
