"""Izin per jam: a one-day Leave Application with a start and end time, approved like any leave.

The employee still works that day, so attendance keeps its status (see overrides/leave_application.py)
and only carries the approved hours in jam_izin; the Salary Slip deducts them through its own jam_izin.
"""

import math

import frappe
from frappe import _
from frappe.utils import to_timedelta


def round_half_hour(hours: float) -> float:
	"""To the nearest 30 minutes, a quarter hour rounding up (Python's round() would go to even)."""
	return math.floor(hours * 2 + 0.5) / 2


def is_hourly(leave_type) -> bool:
	return bool(leave_type and frappe.get_cached_value("Leave Type", leave_type, "izin_per_jam"))


def validate_hourly_leave(doc, method=None):
	"""before_validate: an hourly leave covers one day and carries its rounded hours; any other leave carries none."""
	doc.izin_per_jam = int(is_hourly(doc.leave_type))
	if not doc.izin_per_jam:
		doc.from_time = doc.to_time = None
		doc.jam_izin = 0
		return
	if not (doc.from_time and doc.to_time):
		frappe.throw(_("Isi Jam Mulai dan Jam Selesai untuk izin per jam."))
	start, end = to_timedelta(doc.from_time), to_timedelta(doc.to_time)
	if end <= start:
		frappe.throw(_("Jam Selesai harus setelah Jam Mulai."))
	doc.to_date = doc.from_date
	doc.half_day = 0
	doc.half_day_date = None
	doc.jam_izin = round_half_hour((end - start).total_seconds() / 3600)
	if not doc.jam_izin:
		frappe.throw(_("Izin per jam dihitung per 30 menit, jadi minimal 15 menit."))


def izin_hours(employee, from_date, to_date) -> float:
	"""Approved hourly leave of the employee whose day falls in the period."""
	return sum(
		frappe.get_all(
			"Leave Application",
			filters={
				"employee": employee,
				"docstatus": 1,
				"status": "Approved",
				"izin_per_jam": 1,
				"from_date": ["between", [from_date, to_date]],
			},
			pluck="jam_izin",
			ignore_permissions=True,
		)
	)


def fill_attendance_izin(doc, method=None):
	"""Attendance validate: an attendance made after the leave was approved still shows its hours."""
	doc.jam_izin = izin_hours(doc.employee, doc.attendance_date, doc.attendance_date)


def stamp_attendance_izin(doc, method=None):
	"""Leave Application on_submit / on_cancel: mark (or clear) the hours on that day's attendance."""
	if not doc.get("izin_per_jam"):
		return
	hours = izin_hours(doc.employee, doc.from_date, doc.from_date)
	for name in frappe.get_all(
		"Attendance",
		filters={"employee": doc.employee, "attendance_date": doc.from_date, "docstatus": ["!=", 2]},
		pluck="name",
		ignore_permissions=True,
	):
		# a column write: a submitted attendance must not be re-validated or re-versioned for a mark
		frappe.db.set_value("Attendance", name, "jam_izin", hours, update_modified=False)


@frappe.whitelist()
def get_hourly_leave_types() -> list:
	"""For the app's leave form: which leave types ask for a start and end time instead of dates."""
	return frappe.get_all("Leave Type", filters={"izin_per_jam": 1}, pluck="name")
