# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""HRM whitelisted APIs.

These extend Frappe HR (attendance gallery, lateness calendar, leave usage)
without modifying the hrms app itself.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, getdate

from hrms.api import get_current_employee, get_holidays_for_calendar


ATTENDANCE_STATUSES = ("Present", "Half Day", "Absent", "On Leave", "Work From Home")
# Filtering logs by the attendance of their day is done in Python, so keep the range small.
MAX_FILTERED_DAYS = 31


@frappe.whitelist()
def get_hr_settings() -> dict:
	settings = frappe.db.get_singles_dict("HR Settings", cast=True)
	return frappe._dict(
		allow_employee_checkin_from_mobile_app=settings.allow_employee_checkin_from_mobile_app,
		allow_geolocation_tracking=settings.allow_geolocation_tracking,
		prevent_self_leave_approval=settings.prevent_self_leave_approval,
		enable_multi_currency_expense_claim=settings.enable_multi_currency_expense_claim,
		enable_face_checkin=settings.get("enable_face_checkin"),
		require_face_checkin=settings.get("require_face_checkin"),
		face_match_threshold=settings.get("face_match_threshold") or 0.5,
		face_enroll_samples=settings.get("face_enroll_samples") or 3,
	)


@frappe.whitelist()
def get_attendance_calendar_events(from_date: str, to_date: str) -> dict:
	employee = get_current_employee()
	holidays = get_holidays_for_calendar(employee, from_date, to_date)
	attendance = get_attendance_for_calendar(employee, from_date, to_date)
	events = {}
	late_days = []
	early_exit_days = []

	date = getdate(from_date)
	while date_diff(to_date, date) >= 0:
		date_str = date.strftime("%Y-%m-%d")
		if date_str in attendance:
			record = attendance[date_str]
			events[date_str] = record["status"]
			if record.get("late_entry"):
				late_days.append(date_str)
			if record.get("early_exit"):
				early_exit_days.append(date_str)
		elif date in holidays:
			events[date_str] = "Holiday"
		date = add_days(date, 1)

	return {
		"events": events,
		"late_days": late_days,
		"early_exit_days": early_exit_days,
		"late_count": len(late_days),
		"early_exit_count": len(early_exit_days),
	}


def get_attendance_for_calendar(employee: str, from_date: str, to_date: str) -> dict[str, dict]:
	attendance = frappe.get_all(
		"Attendance",
		{"employee": employee, "attendance_date": ["between", [from_date, to_date]], "docstatus": 1},
		["attendance_date", "status", "late_entry", "early_exit"],
	)
	return {str(d["attendance_date"]): d for d in attendance}


@frappe.whitelist()
def get_leave_usage_summary(year: int | None = None) -> list[dict]:
	"""Count of leave applications per leave type for the year (excludes cancelled/rejected)."""
	from frappe.utils import flt

	employee = get_current_employee()
	year = year or getdate().year

	applications = frappe.get_all(
		"Leave Application",
		filters={
			"employee": employee,
			"from_date": ["between", [f"{year}-01-01", f"{year}-12-31"]],
			"docstatus": ["<", 2],
			"status": ["!=", "Rejected"],
		},
		fields=["leave_type", "total_leave_days"],
	)

	summary = {}
	for application in applications:
		row = summary.setdefault(
			application.leave_type,
			{"leave_type": application.leave_type, "count": 0, "days": 0.0},
		)
		row["count"] += 1
		row["days"] += flt(application.total_leave_days)

	return sorted(summary.values(), key=lambda row: row["leave_type"])


@frappe.whitelist()
def get_leave_types(employee: str, date: str) -> list:
	from hrms.hr.doctype.leave_application.leave_application import get_leave_details

	date = date or getdate()

	# Get leave details validate leave access internally
	leave_details = get_leave_details(employee, date)
	leave_types = list(leave_details["leave_allocation"].keys()) + leave_details["lwps"]

	# include no-allocation leave types (e.g. permission/izin) that allow a
	# negative balance, so they show up even without an allocation
	no_allocation_types = frappe.get_all(
		"Leave Type",
		filters={"allow_negative": 1, "is_lwp": 0},
		pluck="name",
	)
	for leave_type in no_allocation_types:
		if leave_type not in leave_types:
			leave_types.append(leave_type)

	return leave_types


def require_page_access(page: str) -> None:
	"""A page's APIs follow the page's roles, managed in Role Permission for Page and Report."""
	if not frappe.get_doc("Page", page).is_permitted():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_employee_gallery_access() -> None:
	require_page_access("employee-attendance-gallery")


def _get_accessible_employees(company: str | None = None) -> list[str]:
	filters = {}
	if company:
		filters["company"] = company
	return frappe.get_list("Employee", filters=filters, pluck="name", limit_page_length=0)


def _attendance_conditions(late_entry=None, early_exit=None, missing_checkout=None, attendance_status=None) -> dict:
	"""Conditions on a day's Attendance, shared by the gallery, the summary and the detail view."""
	conditions = {
		fieldname: 1
		for fieldname, value in (
			("late_entry", late_entry),
			("early_exit", early_exit),
			("missing_checkout", missing_checkout),
		)
		if cint(value)
	}
	if attendance_status in ATTENDANCE_STATUSES:
		conditions["status"] = attendance_status
	return conditions


@frappe.whitelist()
def get_employee_checkin_gallery(
	company: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	employee: str | None = None,
	search: str | None = None,
	log_type: str | None = None,
	face_verified: str | int | None = None,
	late_entry: str | int | None = None,
	early_exit: str | int | None = None,
	missing_checkout: str | int | None = None,
	attendance_status: str | None = None,
	start: int = 0,
	page_length: int = 24,
) -> dict:
	"""Card gallery of employee check-in logs with the attendance status of that day.

	late_entry / early_exit / missing_checkout / attendance_status keep only logs whose day's
	Attendance matches all of the selected conditions.
	"""
	_require_employee_gallery_access()

	to_date = getdate(to_date) if to_date else getdate()
	from_date = getdate(from_date) if from_date else to_date
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	accessible = _get_accessible_employees(company)
	if employee:
		if employee not in accessible:
			frappe.throw(_("Not permitted for employee {0}").format(employee), frappe.PermissionError)
		accessible = [employee]
	if not accessible:
		return {"rows": [], "has_more": False}

	conditions = _attendance_conditions(late_entry, early_exit, missing_checkout, attendance_status)
	matching_days = None
	if conditions:
		if date_diff(to_date, from_date) > MAX_FILTERED_DAYS:
			frappe.throw(_("Pilih rentang maksimal {0} hari saat memakai filter attendance.").format(MAX_FILTERED_DAYS))
		matching_days = {
			(row.employee, str(row.attendance_date))
			for row in frappe.get_all(
				"Attendance",
				filters={
					"employee": ["in", accessible],
					"attendance_date": ["between", [from_date, to_date]],
					"docstatus": 1,
					**conditions,
				},
				fields=["employee", "attendance_date"],
				limit_page_length=0,
			)
		}
		if not matching_days:
			return {"rows": [], "has_more": False}
		accessible = sorted({row_employee for row_employee, _day in matching_days})

	start = cint(start) or 0
	page_length = min(cint(page_length) or 24, 100)

	filters = {
		"employee": ["in", accessible],
		"time": ["between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]],
	}
	if log_type in ("IN", "OUT"):
		filters["log_type"] = log_type
	if face_verified not in (None, "", "all"):
		filters["face_verified"] = cint(face_verified)
	if search:
		filters["employee_name"] = ["like", f"%{search}%"]

	checkins = frappe.get_all(
		"Employee Checkin",
		filters=filters,
		fields=[
			"name",
			"employee",
			"employee_name",
			"log_type",
			"time",
			"face_verified",
			"face_score",
			"face_photo",
			"outlet_at_checkin",
			"shift",
			"latitude",
			"longitude",
		],
		order_by="time desc",
		# With attendance conditions the page is cut after filtering, below.
		**({"limit_page_length": 0} if matching_days is not None else {"start": start, "page_length": page_length + 1}),
	)
	if matching_days is not None:
		checkins = [row for row in checkins if (row.employee, str(getdate(row.time))) in matching_days][start:]
	has_more = len(checkins) > page_length
	checkins = checkins[:page_length]
	if not checkins:
		return {"rows": [], "has_more": False}

	employee_names = list({row.employee for row in checkins})
	employees = {
		row.name: row
		for row in frappe.get_all(
			"Employee",
			filters={"name": ["in", employee_names]},
			fields=["name", "company", "designation"],
		)
	}

	attendance_map = {}
	for row in frappe.get_all(
		"Attendance",
		filters={
			"employee": ["in", employee_names],
			"attendance_date": ["between", [from_date, to_date]],
			"docstatus": 1,
		},
		fields=["employee", "attendance_date", "status", "late_entry", "early_exit"],
	):
		attendance_map[(row.employee, str(row.attendance_date))] = row

	for checkin in checkins:
		employee_row = employees.get(checkin.employee) or {}
		checkin["company"] = employee_row.get("company")
		checkin["designation"] = employee_row.get("designation")
		attendance = attendance_map.get((checkin.employee, str(getdate(checkin.time))))
		checkin["attendance_status"] = attendance.status if attendance else None
		checkin["late_entry"] = attendance.late_entry if attendance else 0
		checkin["early_exit"] = attendance.early_exit if attendance else 0

	return {"rows": checkins, "has_more": has_more}


@frappe.whitelist()
def get_attendance_daily_cards(
	employee: str,
	from_date: str,
	to_date: str,
	late_entry: str | int | None = None,
	early_exit: str | int | None = None,
	missing_checkout: str | int | None = None,
	attendance_status: str | None = None,
) -> dict:
	"""Per-day attendance cards for one employee (drill-down of the gallery).

	The same attendance conditions as the gallery keep only the days that match.
	"""
	_require_employee_gallery_access()
	frappe.has_permission("Employee", "read", employee, throw=True)

	from_date = getdate(from_date)
	to_date = getdate(to_date)
	conditions = _attendance_conditions(late_entry, early_exit, missing_checkout, attendance_status)

	checkins = frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": employee,
			"time": ["between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]],
		},
		fields=[
			"name",
			"log_type",
			"time",
			"face_verified",
			"face_score",
			"face_photo",
			"outlet_at_checkin",
			"shift",
			"latitude",
			"longitude",
		],
		order_by="time asc",
		limit_page_length=0,
	)

	attendance = {
		str(row.attendance_date): row
		for row in frappe.get_all(
			"Attendance",
			filters={
				"employee": employee,
				"attendance_date": ["between", [from_date, to_date]],
				"docstatus": 1,
			},
			fields=[
				"attendance_date",
				"status",
				"late_entry",
				"early_exit",
				"missing_checkout",
				"in_time",
				"out_time",
				"working_hours",
			],
		)
	}

	logs_by_date = {}
	for checkin in checkins:
		logs_by_date.setdefault(str(getdate(checkin.time)), []).append(checkin)

	days = []
	date = from_date
	while date <= to_date:
		date_str = str(date)
		logs = logs_by_date.get(date_str, [])
		attendance_row = attendance.get(date_str)
		matches = not conditions or (
			attendance_row and all(attendance_row.get(key) == value for key, value in conditions.items())
		)
		if (logs or attendance_row) and matches:
			first_in = next((log for log in logs if log.log_type == "IN"), logs[0] if logs else None)
			last_out = next((log for log in reversed(logs) if log.log_type == "OUT"), None)
			days.append(
				{
					"date": date_str,
					"status": attendance_row.status if attendance_row else None,
					"late_entry": attendance_row.late_entry if attendance_row else 0,
					"early_exit": attendance_row.early_exit if attendance_row else 0,
					"first_in": first_in,
					"last_out": last_out,
					"logs": logs,
				}
			)
		date = add_days(date, 1)

	employee_info = frappe.db.get_value(
		"Employee", employee, ["employee_name", "company", "designation"], as_dict=True
	)
	return {"employee": employee_info, "days": days}


@frappe.whitelist()
def get_attendance_summary_by_employee(
	company: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	search: str | None = None,
	late_entry: str | int | None = None,
	early_exit: str | int | None = None,
	missing_checkout: str | int | None = None,
	attendance_status: str | None = None,
	start: int = 0,
	page_length: int = 20,
) -> dict:
	"""Per-employee attendance summary for a longer date range (weekly/monthly view).

	With late_entry / early_exit / missing_checkout / attendance_status only employees that have
	at least one day matching all selected conditions are listed.
	"""
	_require_employee_gallery_access()

	to_date = getdate(to_date) if to_date else getdate()
	from_date = getdate(from_date) if from_date else to_date

	filters = {"company": company} if company else {}
	if search:
		filters["employee_name"] = ["like", f"%{search}%"]

	conditions = _attendance_conditions(late_entry, early_exit, missing_checkout, attendance_status)
	if conditions:
		matching = frappe.get_all(
			"Attendance",
			filters={"attendance_date": ["between", [from_date, to_date]], "docstatus": 1, **conditions},
			pluck="employee",
			distinct=True,
			limit_page_length=0,
		)
		if not matching:
			return {"rows": [], "has_more": False}
		filters["name"] = ["in", sorted(matching)]

	start = cint(start) or 0
	page_length = min(cint(page_length) or 20, 100)

	employees = frappe.get_list(
		"Employee",
		filters=filters,
		fields=["name", "employee_name", "company", "designation"],
		order_by="employee_name asc",
		start=start,
		page_length=page_length + 1,
	)
	has_more = len(employees) > page_length
	employees = employees[:page_length]
	if not employees:
		return {"rows": [], "has_more": False}

	employee_names = [row.name for row in employees]
	placeholders = ", ".join(["%s"] * len(employee_names))

	attendance_counts = frappe.db.sql(
		f"""
		SELECT employee,
			SUM(CASE WHEN status IN ('Present', 'Work From Home') THEN 1 ELSE 0 END) AS present,
			SUM(CASE WHEN status = 'Half Day' THEN 1 ELSE 0 END) AS half_day,
			SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) AS absent,
			SUM(CASE WHEN status = 'On Leave' THEN 1 ELSE 0 END) AS on_leave,
			SUM(CASE WHEN late_entry = 1 THEN 1 ELSE 0 END) AS late,
			SUM(CASE WHEN early_exit = 1 THEN 1 ELSE 0 END) AS early,
			SUM(CASE WHEN missing_checkout = 1 THEN 1 ELSE 0 END) AS missing_checkout
		FROM `tabAttendance`
		WHERE employee IN ({placeholders})
			AND attendance_date BETWEEN %s AND %s
			AND docstatus = 1
		GROUP BY employee
		""",
		employee_names + [from_date, to_date],
		as_dict=True,
	)

	log_counts = frappe.db.sql(
		f"""
		SELECT employee, COUNT(*) AS logs
		FROM `tabEmployee Checkin`
		WHERE employee IN ({placeholders})
			AND time BETWEEN %s AND %s
		GROUP BY employee
		""",
		employee_names + [f"{from_date} 00:00:00", f"{to_date} 23:59:59"],
		as_dict=True,
	)

	attendance_map = {row.employee: row for row in attendance_counts}
	log_map = {row.employee: row.logs for row in log_counts}

	rows = []
	for employee_row in employees:
		counts = attendance_map.get(employee_row.name) or {}
		rows.append(
			{
				"employee": employee_row.name,
				"employee_name": employee_row.employee_name,
				"company": employee_row.company,
				"designation": employee_row.designation,
				"present": cint(counts.get("present")),
				"half_day": cint(counts.get("half_day")),
				"absent": cint(counts.get("absent")),
				"on_leave": cint(counts.get("on_leave")),
				"late": cint(counts.get("late")),
				"early": cint(counts.get("early")),
				"missing_checkout": cint(counts.get("missing_checkout")),
				"logs": cint(log_map.get(employee_row.name)),
			}
		)

	return {"rows": rows, "has_more": has_more}
