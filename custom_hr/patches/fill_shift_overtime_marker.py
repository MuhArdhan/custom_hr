"""Shift Types that allow overtime but carry no Overtime Type: stamp the marker the Shift Type now fills itself.

Without it HRMS records no actual overtime on their Attendance. A plain column write: no Shift Type
validation or auto-attendance side effects run.
"""

import frappe

from custom_hr.overrides.shift_type import overtime_marker


def execute():
	names = frappe.get_all(
		"Shift Type", filters={"allow_overtime": 1, "overtime_type": ["in", ["", None]]}, pluck="name"
	)
	if not names:
		return
	marker = overtime_marker()
	if not marker:
		print(f"fill_shift_overtime_marker: no Overtime Type exists; {len(names)} overtime-allowing shift(s) left empty: {names}")
		return
	for name in names:
		frappe.db.set_value("Shift Type", name, "overtime_type", marker, update_modified=False)
	print(f"fill_shift_overtime_marker: {marker} stamped on {names}")
