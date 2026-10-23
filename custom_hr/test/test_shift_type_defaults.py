"""New Shift Types start with the attendance policy HR normally wants; shipped as Property Setters."""

import json
import unittest
from pathlib import Path

from custom_hr import hooks

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "property_setter.json"

EXPECTED = {
	# Also reveals the late/early settings section, which depends on this checkbox.
	"enable_auto_attendance": "1",
	# 0 = no half-day rule (any IN+OUT is Present); HR can still set a threshold per shift.
	"working_hours_threshold_for_half_day": "0",
	"late_entry_grace_period": "5",
	"early_exit_grace_period": "0",
	# The grace periods are ignored unless their marking is switched on.
	"enable_late_entry_marking": "1",
	"enable_early_exit_marking": "1",
}


def default_setters():
	rows = json.loads(FIXTURES.read_text())
	return {
		row["field_name"]: row["value"]
		for row in rows
		if row["doc_type"] == "Shift Type" and row["property"] == "default"
	}


def exported_list():
	for fixture in hooks.fixtures:
		if fixture["doctype"] == "Property Setter":
			return fixture["filters"][0][2]
	return []


def exported_names():
	return set(exported_list())


class TestShiftTypeDefaults(unittest.TestCase):
	def test_new_shift_types_prefill_the_agreed_policy(self):
		self.assertEqual(default_setters(), EXPECTED)

	def test_they_are_exported_with_the_app(self):
		# A name missing from hooks.fixtures is dropped at the next export-fixtures.
		for field in EXPECTED:
			self.assertIn(f"Shift Type-{field}-default", exported_names())

	def test_the_export_list_has_no_repeated_names(self):
		names = exported_list()
		self.assertEqual(len(names), len(set(names)))

	def test_each_setter_is_a_default_on_the_docfield(self):
		for row in json.loads(FIXTURES.read_text()):
			if row["doc_type"] == "Shift Type" and row["property"] == "default":
				self.assertEqual(row["doctype_or_field"], "DocField")
				self.assertEqual(row["name"], f"Shift Type-{row['field_name']}-default")
