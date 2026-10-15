# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Keep native sources working on shared shifts; outlet sessions use T08/T09."""

import frappe
from frappe import _
from frappe.utils import get_datetime, get_time

from hrms.hr.doctype.shift_type.shift_type import ShiftType as BaseShiftType
from hrms.hr.doctype.shift_assignment.shift_assignment import get_employee_shift

from custom_hr.services.outlet_scheduler import native_absence_is_managed


class CustomShiftType(BaseShiftType):
	def _native_logs(self, logs):
		if not logs:
			return []
		# Recheck persisted provenance even when _process receives queued/cached
		# logs without custom fields. NULL/empty legacy sources remain native.
		outlet_names = set(frappe.get_all(
			"Employee Checkin", filters={"name": ["in", [row["name"] for row in logs]], "attendance_source": "Outlet"}, pluck="name",
		))
		return [row for row in logs if row["name"] not in outlet_names]

	def mark_absent_for_dates_with_no_attendance(self, employee):
		frappe.db.get_value("Employee", employee, "name", for_update=True)
		return super().mark_absent_for_dates_with_no_attendance(employee)

	def get_employee_checkins(self):
		return self._native_logs(super().get_employee_checkins())

	def _process(self, logs):
		return super()._process(self._native_logs(logs))

	def get_dates_for_attendance(self, employee):
		return [day for day in super().get_dates_for_attendance(employee) if not native_absence_is_managed(employee, day)]

	def mark_absent_for_half_day_dates(self, employee):
		# Native has no date-filter hook here. Retain its algorithm verbatim for
		# unmanaged dates, but never infer Absent for outlet-owned half days.
		rows = frappe.get_all(
			"Attendance", filters={"employee": employee, "status": "Half Day", "modify_half_day_status": 1, "attendance_date": ["<=", get_datetime(self.last_sync_of_checkin).date()]},
			fields=["name", "attendance_date"],
		)
		for row in rows:
			if native_absence_is_managed(employee, row.attendance_date):
				continue
			timestamp = get_datetime(f"{row.attendance_date} {get_time(self.start_time)}")
			details = get_employee_shift(employee, timestamp, True)
			if details and details.shift_type.name == self.name and details.actual_end < get_datetime(self.last_sync_of_checkin):
				frappe.db.set_value("Attendance", row.name, {"shift": self.name, "half_day_status": "Absent", "modify_half_day_status": 0})
				frappe.get_doc({"doctype": "Comment", "comment_type": "Comment", "reference_doctype": "Attendance", "reference_name": row.name, "content": _("Employee was marked Absent for other half due to missing Employee Checkins.")}).insert(ignore_permissions=True)
