"""Every Shift Type allows overtime and carries the Overtime Type marker the Shift Type now fills itself.

New Shift Types get Allow Overtime by default (Property Setter); this brings the existing ones in line.
Allowing overtime only records actual overtime on Attendance: pay still needs an approved Overtime
Request and is capped at its hours. Plain column writes: no Shift Type validation or auto-attendance runs.
"""

import frappe

from custom_hr.overrides.shift_type import overtime_marker


def execute():
	names = frappe.get_all("Shift Type", pluck="name")
	if not names:
		return
	marker = overtime_marker()
	if not marker:
		print(f"fill_shift_overtime_marker: no Overtime Type exists; Allow Overtime left as it was on {len(names)} shift(s)")
		return
	changed = []
	for row in frappe.get_all("Shift Type", fields=["name", "allow_overtime", "overtime_type"]):
		values = {}
		if not row.allow_overtime:
			values["allow_overtime"] = 1
		if not row.overtime_type or not frappe.db.exists("Overtime Type", row.overtime_type):
			values["overtime_type"] = marker
		if values:
			frappe.db.set_value("Shift Type", row.name, values, update_modified=False)
			changed.append(row.name)
	print(f"fill_shift_overtime_marker: Allow Overtime with {marker} on {changed}")
