"""Two-way sync between approved Overtime Requests and Attendance overtime summary fields."""

from __future__ import annotations

import frappe
from frappe.utils import flt, getdate

from custom_hr.api.overtime_pay import approved_overtime_requests


def paid_hours(actual_hours: float, approved_hours: float) -> float:
	"""Compute payable overtime hours capped by approved hours, matching payroll calculation."""
	actual = flt(actual_hours)
	approved = flt(approved_hours)
	if actual <= 0 or approved <= 0:
		return 0.0
	return flt(min(actual, approved), 2)


def _resolved_values(
	employee: str,
	day,
	actual_overtime_duration: float,
	*,
	exclude_request: str | None = None,
) -> dict:
	empty = {
		"overtime_request": None,
		"overtime_type": None,
		"approved_overtime_hours": 0.0,
		"paid_overtime_hours": 0.0,
	}
	if not employee or not day:
		return empty

	target_day = getdate(day)
	planned = approved_overtime_requests(
		target_day,
		target_day,
		employee=employee,
		exclude_request=exclude_request,
	)
	info = planned.get((employee, target_day))
	if not info:
		return empty

	approved = flt(info.hours, 2)
	return {
		"overtime_request": info.request,
		"overtime_type": info.get("overtime_type") or None,
		"approved_overtime_hours": approved,
		"paid_overtime_hours": paid_hours(actual_overtime_duration, approved),
	}


def fill_attendance_overtime(doc, method=None) -> None:
	"""Attendance validate / on_update_after_submit: sync approved overtime onto the doc."""
	values = _resolved_values(doc.employee, doc.attendance_date, doc.actual_overtime_duration)
	for field, val in values.items():
		setattr(doc, field, val)


def stamp_employee_date(employee: str, day, *, exclude_request: str | None = None) -> None:
	"""Update all active Attendance rows for (employee, day) without triggering re-submission."""
	if not employee or not day:
		return

	target_day = getdate(day)
	attendances = frappe.get_all(
		"Attendance",
		filters={"employee": employee, "attendance_date": target_day, "docstatus": ["!=", 2]},
		fields=[
			"name",
			"actual_overtime_duration",
			"overtime_type",
			"overtime_request",
			"approved_overtime_hours",
			"paid_overtime_hours",
		],
		ignore_permissions=True,
	)
	for att in attendances:
		values = _resolved_values(
			employee,
			target_day,
			att.actual_overtime_duration,
			exclude_request=exclude_request,
		)
		changed = any(
			(
				att.get(field) != val
				if field in ("overtime_request", "overtime_type")
				else flt(att.get(field), 2) != flt(val, 2)
			)
			for field, val in values.items()
		)
		if changed:
			frappe.db.set_value("Attendance", att.name, values, update_modified=False)


def _sync_request(doc, *, exclude_request: str | None = None) -> None:
	days = []
	if doc.get("date"):
		days.append(doc.date)
	get_before = getattr(doc, "get_doc_before_save", None)
	before = get_before() if callable(get_before) else None
	if before and before.get("date") and getdate(before.date) != getdate(doc.date):
		days.append(before.date)

	employees = {row.employee for row in (doc.get("employees") or ()) if row.get("employee")}
	for day in days:
		for employee in employees:
			stamp_employee_date(employee, day, exclude_request=exclude_request)


def stamp_request_attendances(doc, method=None) -> None:
	"""Overtime Request on_update: stamp approved overtime onto existing Attendance rows."""
	_sync_request(doc)


def clear_request_attendances(doc, method=None) -> None:
	"""Overtime Request on_trash: re-evaluate Attendance rows excluding the deleted request."""
	_sync_request(doc, exclude_request=doc.name)


def sync_existing_attendances() -> None:
	"""after_migrate: backfill approved Overtime Request info onto existing Attendance records."""
	if not frappe.db.has_column("Attendance", "overtime_request"):
		return

	pairs: set[tuple[str, object]] = set()
	requests = frappe.get_all(
		"Overtime Request",
		filters={"status": ["!=", "Ditolak"]},
		fields=["name", "date"],
		ignore_permissions=True,
	)
	if requests:
		date_by_req = {r.name: getdate(r.date) for r in requests if r.date}
		for row in frappe.get_all(
			"Overtime Request Employee",
			filters={"parent": ["in", list(date_by_req)]},
			fields=["parent", "employee"],
			ignore_permissions=True,
		):
			if row.employee and row.parent in date_by_req:
				pairs.add((row.employee, date_by_req[row.parent]))

	for field in ("overtime_request", "overtime_type"):
		for att in frappe.get_all(
			"Attendance",
			filters={field: ["is", "set"], "docstatus": ["!=", 2]},
			fields=["employee", "attendance_date"],
			ignore_permissions=True,
		):
			if att.employee and att.attendance_date:
				pairs.add((att.employee, getdate(att.attendance_date)))

	for employee, day in sorted(pairs, key=lambda p: (str(p[1]), p[0])):
		stamp_employee_date(employee, day)
