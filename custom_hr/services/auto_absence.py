"""Absent for scheduled days that carry no sign of work, leave or a manual shift.

`absent_dates` is the shared rule: it takes any shift table (Department now; an Outlet can pass a
per-employee schedule later) and the days already accounted for. `mark_department_absences` is the
daily job for Departments with auto shift, from their effective date onward.
"""

from datetime import date, datetime, time, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, getdate, today
from hrms.utils.holiday_list import get_holiday_dates_between_range

from custom_hr.services.outlet_shift import active_shift_names

SOURCE = "Department"


def absent_dates(rows, start: date, end: date, holidays, covered) -> list[date]:
	"""Days in [start, end] that have an enabled shift in `rows` and are neither a holiday nor covered."""
	skip = set(holidays) | set(covered)
	days, day = [], start
	while day <= end:
		if day not in skip and active_shift_names(rows, day):
			days.append(day)
		day += timedelta(days=1)
	return days


def first_full_day(stamp) -> date:
	"""Auto shift starts mid-day; that day's earlier logs used the native path, so begin the next day."""
	stamp = get_datetime(stamp)
	return stamp.date() + timedelta(days=int(stamp.time() != time.min))


def _each_day(start, end):
	day = getdate(start)
	while day <= getdate(end):
		yield day
		day += timedelta(days=1)


def covered_dates(employee: str, start: date, end: date) -> set[date]:
	"""Days with attendance (an Absent HR cancelled included), a check-in, approved leave or a Shift Assignment."""
	covered = set()
	for row in frappe.get_all(
		"Attendance",
		filters={"employee": employee, "attendance_date": ["between", [start, end]]},
		fields=["attendance_date", "docstatus", "status"],
	):
		# a cancelled Absent is HR's decision for that day; anything else cancelled leaves the day open
		if row.docstatus < 2 or row.status == "Absent":
			covered.add(getdate(row.attendance_date))
	for row in frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee, "time": ["between", [datetime.combine(start, time.min), datetime.combine(end, time.max)]]},
		fields=["time", "shift_work_date"],
	):
		covered.add(getdate(row.shift_work_date or row.time))
	for row in frappe.get_all(
		"Leave Application",
		filters={"employee": employee, "docstatus": 1, "status": "Approved", "from_date": ["<=", end], "to_date": [">=", start]},
		fields=["from_date", "to_date"],
	):
		covered.update(_each_day(max(getdate(row.from_date), start), min(getdate(row.to_date), end)))
	for row in frappe.get_all(
		"Shift Assignment",
		filters={"employee": employee, "docstatus": 1, "status": "Active", "start_date": ["<=", end]},
		or_filters=[["end_date", ">=", start], ["end_date", "is", "not set"]],
		fields=["start_date", "end_date"],
	):
		# native auto attendance owns days with a manual shift
		covered.update(_each_day(max(getdate(row.start_date), start), min(getdate(row.end_date or end), end)))
	return covered


def _mark_absent(employee, day, rows):
	shifts = active_shift_names(rows, day)
	doc = frappe.get_doc(
		{
			"doctype": "Attendance",
			"employee": employee.name,
			"company": employee.company,
			"attendance_date": day,
			"status": "Absent",
			"shift": shifts[0] if len(shifts) == 1 else None,
			"attendance_source": SOURCE,
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
	doc.add_comment("Comment", _("Ditandai Absent karena tidak ada check-in di hari terjadwal Department."))


def mark_department_absences(until: date | None = None) -> int:
	"""Daily job: Absent for every scheduled, uncovered day up to yesterday, from each Department's effective date."""
	until = getdate(until or add_days(today(), -1))  # today is still open
	marked = 0
	for department in frappe.get_all(
		"Department", filters={"enable_auto_shift": 1, "auto_shift_effective_from": ["is", "set"]},
		fields=["name", "auto_shift_effective_from"],
	):
		rows = frappe.get_all(
			"Outlet Shift", filters={"parent": department.name, "parenttype": "Department", "enabled": 1},
			fields=["shift_type", "enabled", "days"],
		)
		if not rows:
			continue
		# shortcut: uses the employee's current Department; a mid-period transfer is judged by today's Department
		for employee in frappe.get_all(
			"Employee", filters={"department": department.name, "status": "Active"},
			fields=["name", "company", "date_of_joining", "relieving_date"],
		):
			start = max(first_full_day(department.auto_shift_effective_from), getdate(employee.date_of_joining or "1900-01-01"))
			end = min(until, getdate(employee.relieving_date)) if employee.relieving_date else until
			if start > end:
				continue
			holidays = get_holiday_dates_between_range(employee.name, start, end, raise_exception_for_holiday_list=False)
			for day in absent_dates(rows, start, end, map(getdate, holidays), covered_dates(employee.name, start, end)):
				frappe.db.savepoint("auto_absence")
				try:
					_mark_absent(employee, day, rows)
					marked += 1
				except Exception:
					frappe.db.rollback(save_point="auto_absence")
					frappe.log_error(title=f"Auto Absent: {employee.name} {day}", reference_doctype="Employee", reference_name=employee.name)
	return marked
