# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Keep native sources working on shared shifts; outlet sessions use T08/T09."""

import frappe
from frappe import _
from frappe.utils import get_datetime, get_time, now_datetime

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
		native = [row for row in logs if row["name"] not in outlet_names]
		departments = self._department_names(native)
		for row in native:
			row["department_mode"] = row["name"] in departments
		return native

	def _department_names(self, logs):
		if not logs:
			return set()
		return set(frappe.get_all(
			"Employee Checkin", filters={"name": ["in", [row["name"] for row in logs]], "attendance_source": "Department"}, pluck="name",
		))

	def _without_open_department_sessions(self, logs):
		"""A Department IN with no OUT is judged only after its check-out deadline (end of the shift day).

		Native pulls last_sync_of_checkin forward after any OUT, which would otherwise close colleagues' open days.
		"""
		groups = {}
		for row in logs:
			groups.setdefault((row.get("employee"), row.get("shift_start")), []).append(row)
		now = now_datetime()
		held = set()
		for group in groups.values():
			open_session = all(row.get("department_mode") for row in group) and not any(row.get("log_type") == "OUT" for row in group)
			if open_session and now <= get_datetime(group[0].get("shift_actual_end")):
				held.update(row["name"] for row in group)
		return [row for row in logs if row["name"] not in held]

	def get_attendance(self, logs, working_hours_threshold_for_absent, working_hours_threshold_for_half_day):
		status, hours, late_entry, early_exit, in_time, out_time = super().get_attendance(
			logs, working_hours_threshold_for_absent, working_hours_threshold_for_half_day
		)
		if in_time and not out_time and logs[0].get("department_mode"):
			# Missing check-out: the day counts as Present with the shift's standard hours
			return "Present", (logs[0].shift_end - logs[0].shift_start).total_seconds() / 3600, late_entry, False, in_time, None
		return status, hours, late_entry, early_exit, in_time, out_time

	def mark_absent_for_dates_with_no_attendance(self, employee):
		frappe.db.get_value("Employee", employee, "name", for_update=True)
		return super().mark_absent_for_dates_with_no_attendance(employee)

	def get_employee_checkins(self):
		return self._without_open_department_sessions(self._native_logs(super().get_employee_checkins()))

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
