"""Attendance list filters: company and department replace the outlet, source and working-hours-source filters."""

import json
import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def fixture(name):
	return json.loads((APP / "fixtures" / name).read_text(encoding="utf-8"))


class TestAttendanceListFilters(unittest.TestCase):
	def test_outlet_and_working_hours_source_are_not_standard_filters(self):
		fields = {row["fieldname"]: row for row in fixture("custom_field.json") if row.get("dt") == "Attendance"}
		for fieldname in ("outlet_at_checkin", "working_hours_source", "attendance_source"):
			with self.subTest(fieldname=fieldname):
				self.assertFalse(fields[fieldname].get("in_standard_filter"))

	def test_company_and_department_are_standard_filters_and_are_shipped(self):
		setters = {row["name"]: row for row in fixture("property_setter.json")}
		hooks = (APP / "hooks.py").read_text(encoding="utf-8")
		for fieldname in ("company", "department"):
			with self.subTest(fieldname=fieldname):
				setter = setters[f"Attendance-{fieldname}-in_standard_filter"]
				self.assertEqual((setter["doc_type"], setter["field_name"], setter["property"], setter["value"]), ("Attendance", fieldname, "in_standard_filter", "1"))
				self.assertIn(f'"Attendance-{fieldname}-in_standard_filter"', hooks)

	def test_attendance_date_is_a_range_filter(self):
		script = (APP / "public" / "js" / "attendance_list.js").read_text(encoding="utf-8")
		self.assertIn('fieldtype: "DateRange"', script)
		self.assertIn('condition: "Between"', script)

	def test_the_employee_name_filter_is_hidden_by_the_attendance_list_script(self):
		script = (APP / "public" / "js" / "attendance_list.js").read_text(encoding="utf-8")
		self.assertTrue(re.search(r"fields_dict\.employee_name", script))
