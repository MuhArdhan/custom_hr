# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Pair-scoped attendance. Internal jobs only, no commits or shift-wide sync.

Employee -> IN -> paired OUTs -> Attendance is the locking order. The outlet
scheduler handles discovery; this module does not scan employees.
"""

from copy import deepcopy
from datetime import datetime, time, timedelta
from math import isclose

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate

from custom_hr.services.outlet_checkin import (
	LOCKED_FIELDS,
	OUT_COPY_FIELDS,
	_canonical,
	_checkout_snapshot,
)
from custom_hr.services.outlet_shift import (
	FLAG_FIELDS,
	_policy,
	normalize_checkin_datetime,
)

LOG_FIELDS = ("name", *LOCKED_FIELDS)
ATTENDANCE_FIELDS = (
	"name", "employee", "attendance_date", "docstatus", "status", "shift",
	"leave_application", "leave_type", "attendance_request", "half_day_status",
	"modify_half_day_status", "attendance_source", "source_checkin", "source_checkout",
)


def _fail(message):
	frappe.throw(message, title=_("Sesi Attendance Outlet Bermasalah"))


def _session_policy(entry):
	snapshot = _checkout_snapshot(entry)
	required = (
		*FLAG_FIELDS, "company", "holiday_list", "holiday_source", "attendance_source",
		"late_entry_grace_period", "early_exit_grace_period",
		"working_hours_threshold_for_half_day", "working_hours_threshold_for_absent",
		"determine_check_in_and_check_out", "working_hours_calculation_based_on",
		"standard_working_hours",
	)
	try:
		if any(field not in snapshot for field in required):
			raise ValueError("incomplete policy")
		policy = _policy({**snapshot, "name": entry.shift})
		standard = (get_datetime(entry.shift_end) - get_datetime(entry.shift_start)).total_seconds() / 3600
		valid = (
			snapshot["company"] and snapshot["holiday_list"]
			# Additive v1 marker: old snapshots retain their original company;
			# never recompute historical logs from either live master.
			and snapshot.get("company_source", "Employee") == "Employee"
			and snapshot["attendance_source"] == "Outlet" and snapshot["holiday_source"] == "Outlet"
			and getdate(entry.shift_work_date) == get_datetime(entry.shift_start).date()
			and get_datetime(entry.checkout_deadline) == datetime.combine(get_datetime(entry.shift_end).date(), time(23, 59, 59))
			and get_datetime(entry.time) >= get_datetime(entry.shift_actual_start)
			and isclose(float(snapshot["standard_working_hours"]), standard, rel_tol=0, abs_tol=1e-9)
		)
		if not valid:
			raise ValueError("inconsistent policy")
	except (ValueError, TypeError, OverflowError):
		_fail(_("Kebijakan snapshot IN tidak lengkap atau tidak konsisten. Master shift tidak dipakai sebagai pengganti."))
	return {**snapshot, **policy}


def _validate_checkout(entry, checkout):
	if (
		checkout.employee != entry.employee or checkout.log_type != "OUT"
		or checkout.paired_checkin != entry.name
	):
		_fail(_("Identitas pasangan IN–OUT tidak sesuai."))
	for field in OUT_COPY_FIELDS:
		try:
			equal = _canonical(field, entry.get(field)) == _canonical(field, checkout.get(field))
		except (TypeError, ValueError, OverflowError):
			equal = False
		if not equal:
			_fail(_("Field {0} OUT tidak sesuai dengan snapshot IN.").format(field))
	if not checkout.time or not get_datetime(entry.time) <= get_datetime(checkout.time) <= get_datetime(entry.checkout_deadline):
		_fail(_("Waktu OUT berada di luar rentang sesi IN yang terkunci."))


def calculate_session_attendance(entry, checkout=None, *, half_holiday=False, finalize_missing=False, now=None):
	"""Pure calculation from persisted logs/policy; never invent missing timestamps."""
	policy = _session_policy(entry)
	in_time = get_datetime(entry.time)
	out_time = None
	if checkout:
		_validate_checkout(entry, checkout)
		out_time = get_datetime(checkout.time)
		working_hours = round((out_time - in_time).total_seconds() / 3600, 2)
	else:
		if not finalize_missing or normalize_checkin_datetime(now) <= get_datetime(entry.checkout_deadline):
			_fail(_("IN-only belum boleh difinalkan sebelum batas OUT terlewati."))
		if policy.get("missing_checkout_status") != "Present" or policy.get("missing_checkout_hours_source") != "Locked Shift Allocation":
			_fail(_("Kebijakan Tidak OUT pada snapshot belum didukung."))
		working_hours = float(policy["standard_working_hours"])
	late = bool(policy["enable_late_entry_marking"] and in_time > get_datetime(entry.shift_start) + timedelta(minutes=policy["late_entry_grace_period"]))
	early = bool(out_time and policy["enable_early_exit_marking"] and out_time < get_datetime(entry.shift_end) - timedelta(minutes=policy["early_exit_grace_period"]))
	divisor = 2 if half_holiday else 1
	absent_threshold = policy["working_hours_threshold_for_absent"] / divisor
	half_threshold = policy["working_hours_threshold_for_half_day"] / divisor
	status = "Present"
	if checkout:
		if absent_threshold and working_hours < absent_threshold:
			status = "Absent"
		elif half_threshold and working_hours < half_threshold:
			status = "Half Day"
	overtime = (
		max(working_hours - float(policy["standard_working_hours"]), 0)
		if checkout and status == "Present" and policy["allow_overtime"] else 0
	)
	return frappe._dict(
		employee=entry.employee, company=policy["company"], attendance_date=getdate(entry.shift_work_date),
		shift=entry.shift, status=status, working_hours=working_hours, in_time=in_time, out_time=out_time,
		late_entry=int(late), early_exit=int(early), standard_working_hours=float(policy["standard_working_hours"]),
		actual_overtime_duration=round(overtime, 2), overtime_type=policy.get("overtime_type") if overtime else None,
		attendance_source="Outlet", outlet_at_checkin=entry.outlet_at_checkin,
		source_checkin=entry.name, source_checkout=checkout.name if checkout else None,
		missing_checkout=int(not checkout), working_hours_source="Actual Logs" if checkout else "Locked Shift Allocation",
	)


def _read_session(source_checkin, source_checkout, *, finalize_missing):
	# Only this initial identity read is non-locking. Re-read all source fields
	# after the employee lock; never use a cached document or earlier snapshot.
	employee = frappe.db.get_value("Employee Checkin", source_checkin, "employee")
	if not employee or not frappe.db.get_value("Employee", employee, "name", for_update=True):
		_fail(_("IN atau Employee sesi tidak ditemukan."))
	entry = frappe.db.get_value("Employee Checkin", source_checkin, list(LOG_FIELDS), as_dict=True, for_update=True)
	if not entry or entry.employee != employee:
		_fail(_("Identitas IN berubah atau tidak ditemukan."))
	policy = _session_policy(entry)
	log = frappe.qb.DocType("Employee Checkin")
	outs = (
		frappe.qb.from_(log).select(*(log[field] for field in LOG_FIELDS))
		.where(log.paired_checkin == source_checkin).orderby(log.name).for_update().run(as_dict=True)
	)
	if source_checkout:
		if len(outs) != 1 or outs[0].name != source_checkout:
			_fail(_("OUT pasangan tidak ditemukan, berbeda, atau lebih dari satu. Sesi tidak diproses secara sembarang."))
		checkout = outs[0]
		_validate_checkout(entry, checkout)
	else:
		if not finalize_missing or outs:
			_fail(_("Finalisasi IN-only memerlukan sesi tanpa OUT; pasangan lengkap harus diproses dengan identitas OUT."))
		checkout = None
	return entry, checkout, policy


def _attendance_for_date(entry):
	table = frappe.qb.DocType("Attendance")
	return (
		frappe.qb.from_(table).select(*(table[field] for field in ATTENDANCE_FIELDS))
		.where((table.employee == entry.employee) & (table.attendance_date == getdate(entry.shift_work_date)))
		.orderby(table.name).for_update().run(as_dict=True)
	)


def _approved_leaves(entry):
	leave = frappe.qb.DocType("Leave Application")
	return (
		frappe.qb.from_(leave).select(leave.name, leave.leave_type, leave.half_day, leave.half_day_date)
		.where(
			(leave.employee == entry.employee) & (leave.docstatus == 1) & (leave.status == "Approved")
			& (leave.from_date <= getdate(entry.shift_work_date)) & (leave.to_date >= getdate(entry.shift_work_date))
		).orderby(leave.name).for_update().run(as_dict=True)
	)


def _holiday_state(policy, work_date):
	if not frappe.db.exists("Holiday List", policy["holiday_list"]):
		_fail(_("Holiday List pada snapshot IN tidak ditemukan."))
	# Do not call employee-specific holiday helpers (or their cached results).
	rows = frappe.get_all(
		"Holiday", filters={"parent": policy["holiday_list"], "holiday_date": work_date}, fields=["is_half_day"],
	)
	return any(not cint(row.is_half_day) for row in rows), any(cint(row.is_half_day) for row in rows)


def _link_logs(entry, checkout, attendance):
	for row in (entry, checkout):
		if row and row.attendance != attendance:
			# Deliberate bounded backend update; do not save()/rewrite locked logs.
			frappe.db.set_value("Employee Checkin", row.name, "attendance", attendance, update_modified=False)


def _process_session(source_checkin, source_checkout, *, finalize_missing=False):
	entry, checkout, policy = _read_session(source_checkin, source_checkout, finalize_missing=finalize_missing)
	if cint(entry.skip_auto_attendance) or cint(entry.offshift):
		return {"status": "skipped", "reason": "skip_auto_attendance"}
	if not checkout and normalize_checkin_datetime() <= get_datetime(entry.checkout_deadline):
		_fail(_("IN-only belum boleh difinalkan sebelum batas OUT terlewati."))
	attendances = _attendance_for_date(entry)
	active = [row for row in attendances if cint(row.docstatus) < 2]
	if len(active) > 1:
		_fail(_("Ada beberapa Attendance pada tanggal kerja ini. Hubungi HR sebelum memproses sesi."))
	linked = {row.attendance for row in (entry, checkout) if row and row.attendance}
	if len(linked) > 1:
		_fail(_("IN dan OUT terhubung ke Attendance yang berbeda."))
	existing = active[0] if active else None
	if linked and (not existing or existing.name not in linked):
		_fail(_("Tautan Attendance sesi tidak sesuai dengan Attendance aktif pada tanggal kerja ini."))
	if existing:
		if cint(existing.docstatus) != 1:
			_fail(_("Attendance draft sudah ada. Selesaikan atau koreksi melalui HR; job tidak menimpanya."))
		if existing.source_checkin and existing.source_checkin != entry.name:
			_fail(_("Attendance sudah memiliki sumber IN sesi lain."))
		if existing.source_checkout and existing.source_checkout != (checkout.name if checkout else None):
			_fail(_("Attendance sudah memiliki sumber OUT sesi lain."))
		if linked:
			_link_logs(entry, checkout, existing.name)
			return {"status": "already_processed", "attendance": existing.name}
	elif attendances:
		# A cancelled result is an administrative decision, not an invitation to
		# recreate it on retry. T09 will also use this guard for recovery scans.
		return {"status": "skipped", "reason": "cancelled_attendance"}
	leaves = _approved_leaves(entry)
	if len(leaves) > 1:
		_fail(_("Ada beberapa cuti disetujui pada tanggal sesi. Hubungi HR."))
	merge_half_day = bool(
		existing and existing.status == "Half Day" and cint(existing.modify_half_day_status)
		and not existing.attendance_request and leaves and cint(leaves[0].half_day) and leaves[0].half_day_date
		and getdate(leaves[0].half_day_date) == getdate(entry.shift_work_date)
		and existing.leave_application == leaves[0].name and existing.leave_type == leaves[0].leave_type
		and not existing.source_checkin
	)
	if existing and not merge_half_day:
		# Official leave/request/manual corrections win. Link for traceability,
		# but do not relabel, recalculate, or overwrite their Attendance fields.
		_link_logs(entry, checkout, existing.name)
		frappe.get_doc("Attendance", existing.name).add_comment(
			text=_("Sesi outlet IN {0}, OUT {1} ditautkan tanpa mengubah Attendance resmi yang sudah ada.").format(entry.name, checkout.name if checkout else _("Tidak OUT"))
		)
		return {"status": "preserved_existing", "attendance": existing.name}
	full_holiday, half_holiday = _holiday_state(policy, getdate(entry.shift_work_date))
	if full_holiday and not policy["mark_auto_attendance_on_holidays"]:
		return {"status": "skipped", "reason": "outlet_holiday"}
	values = calculate_session_attendance(entry, checkout, half_holiday=half_holiday, finalize_missing=finalize_missing)
	if leaves:
		leave = leaves[0]
		is_half = bool(cint(leave.half_day) and leave.half_day_date and getdate(leave.half_day_date) == values.attendance_date)
		values.update(
			leave_application=leave.name, leave_type=leave.leave_type,
			half_day_status=("Absent" if values.status == "Absent" else "Present") if is_half else None,
			modify_half_day_status=0, status="Half Day" if is_half else "On Leave",
			actual_overtime_duration=0, overtime_type=None,
		)
	if merge_half_day:
		values.pop("employee")
		values.pop("company")
		values.pop("attendance_date")
		frappe.db.set_value("Attendance", existing.name, dict(values))
		name = existing.name
		frappe.get_doc("Attendance", name).publish_update()
	else:
		doc = frappe.get_doc({"doctype": "Attendance", **values})
		# Native company.fetch_from=employee.company otherwise overwrites the
		# locked source company after a transfer, both on insert and submit.
		# Isolate metadata on this backend-created document only; keep normal
		# Link validation and never mutate shared meta/Property Setters.
		doc.meta = deepcopy(doc.meta)
		doc.meta.get_field("company").fetch_if_empty = 1
		doc.insert(ignore_permissions=True)
		doc.submit()  # Keep native date/duplicate/leave validation and lifecycle.
		name = doc.name
	_link_logs(entry, checkout, name)
	return {"status": "updated_half_day" if merge_half_day else "created", "attendance": name}


def process_outlet_attendance(source_checkin: str, source_checkout: str | None = None, *, finalize_missing=False):
	"""Internal queue entry point; not whitelisted. Caller owns commit/rollback.

	The outlet scheduler calls finalize_missing only after the stored deadline.
	Failures revert only this session and include both IDs in a deferred Error Log.
	"""
	user = frappe.session.user
	frappe.set_user("Administrator")
	frappe.db.savepoint("outlet_attendance_session")
	try:
		return _process_session(source_checkin, source_checkout, finalize_missing=finalize_missing)
	except Exception:
		traceback = frappe.get_traceback()
		try:
			frappe.db.rollback(save_point="outlet_attendance_session")
		except Exception:
			# InnoDB may already have rolled back the whole transaction on a
			# deadlock. Preserve the original exception for the queue's retry
			# handling and include both traces rather than losing the session ID.
			traceback += "\nSavepoint rollback failed:\n" + frappe.get_traceback()
		frappe.log_error(
			title="Outlet attendance session failed",
			message=f"IN: {source_checkin}\nOUT: {source_checkout or '(missing)'}\n{traceback}",
			reference_doctype="Employee Checkin", reference_name=source_checkin, defer_insert=True,
		)
		raise
	finally:
		frappe.set_user(user)
