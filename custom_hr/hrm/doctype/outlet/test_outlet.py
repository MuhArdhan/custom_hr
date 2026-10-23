# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""T03 validation/schema tests. No Employee, Checkin or Attendance writes."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe

from custom_hr.hrm.doctype.outlet.outlet import SHIFT_NUMERIC_FIELDS, Outlet
from custom_hr.patches.add_outlet_shift_fields import (
	OUTLET_SHIFT_FIELDS,
	execute,
	get_outlet_shift_custom_fields,
)


class TestOutletConfiguration(unittest.TestCase):
	def setUp(self):
		self.outlet = frappe.get_doc(
			{
				"doctype": "Outlet",
				"company": "_Test Outlet Company",
				"is_active": 1,
				"holiday_list": "_Test Outlet Holiday",
				"shift_transition_minutes": 30,
				"enable_outlet_auto_shift": 0,
			}
		)
		self.shifts = []

	def tearDown(self):
		frappe.clear_messages()

	def add_shift(self, name="Shift A", start="05:00:00", end="13:00:00", enabled=1):
		self.outlet.append("shifts", {"shift_type": name, "enabled": enabled})
		shift = frappe._dict(name=name, start_time=start, end_time=end)
		shift.update(dict.fromkeys(SHIFT_NUMERIC_FIELDS, 0))
		self.shifts.append(shift)
		return shift

	def validate(self):
		with patch("custom_hr.hrm.doctype.outlet.outlet.frappe.get_all", return_value=self.shifts) as query:
			self.outlet.validate()
			return query

	def test_disabled_outlet_without_shifts_is_valid(self):
		self.assertFalse(self.validate().called)

	def test_pilot_overlap_is_allowed_and_queried_once(self):
		self.add_shift()
		self.add_shift("Shift B", "10:00:00", "18:00:00")
		self.validate().assert_called_once()
		self.assertEqual(self.outlet.shift_transition_minutes, 30)

	def test_zero_transition_is_valid(self):
		self.outlet.shift_transition_minutes = 0
		self.validate()

	def test_numeric_string_transition_is_normalized(self):
		self.outlet.shift_transition_minutes = "30"
		self.validate()
		self.assertEqual(self.outlet.shift_transition_minutes, 30)

	def test_invalid_transition_values_are_rejected(self):
		for value in (-1, "-0.5", "NaN", "Infinity", "not a number", None):
			with self.subTest(value=value), self.assertRaisesRegex(frappe.ValidationError, "angka tidak negatif"):
				self.outlet.shift_transition_minutes = value
				self.validate()

	def test_fractional_minutes_are_rejected(self):
		self.outlet.shift_transition_minutes = "0.5"
		with self.assertRaisesRegex(frappe.ValidationError, "bilangan bulat"):
			self.validate()

	def test_transition_cannot_span_a_whole_day(self):
		for value in (1440, 1441):
			with self.subTest(value=value), self.assertRaisesRegex(frappe.ValidationError, "kurang dari 1440"):
				self.outlet.shift_transition_minutes = value
				self.validate()

	def test_duplicate_shift_even_if_disabled_is_rejected(self):
		self.add_shift()
		self.outlet.append("shifts", {"shift_type": "Shift A", "enabled": 0})
		with self.assertRaisesRegex(frappe.ValidationError, "lebih dari sekali"):
			self.validate()

	def test_missing_shift_type_is_rejected(self):
		self.outlet.append("shifts", {"enabled": 1})
		with self.assertRaisesRegex(frappe.ValidationError, "Shift Type wajib diisi"):
			self.validate()

	def test_deleted_shift_type_is_rejected(self):
		self.outlet.append("shifts", {"shift_type": "Missing Shift", "enabled": 1})
		with self.assertRaisesRegex(frappe.ValidationError, "tidak ditemukan"):
			self.validate()

	def test_same_start_on_two_active_shifts_is_rejected(self):
		self.add_shift()
		self.add_shift("Shift B", "05:00:00", "15:00:00")
		with self.assertRaisesRegex(frappe.ValidationError, "jam mulai yang sama"):
			self.validate()

	def test_disabled_shift_does_not_conflict_with_active_start(self):
		self.add_shift()
		self.add_shift("Shift B", "05:00:00", "15:00:00", enabled=0)
		self.validate()

	def test_overnight_shift_is_not_rejected_as_overlap(self):
		self.add_shift(start="22:00:00", end="06:00:00")
		self.validate()

	def test_same_start_and_end_is_rejected(self):
		self.add_shift(start="05:00:00", end="05:00:00")
		with self.assertRaisesRegex(frappe.ValidationError, "tidak boleh sama"):
			self.validate()

	def test_missing_shift_times_are_rejected(self):
		shift = self.add_shift()
		for field in ("start_time", "end_time"):
			with self.subTest(field=field), self.assertRaisesRegex(frappe.ValidationError, "wajib diisi"):
				old = shift[field]
				shift[field] = None
				try:
					self.validate()
				finally:
					shift[field] = old

	def test_negative_shift_tolerances_and_thresholds_are_rejected(self):
		shift = self.add_shift()
		for field in SHIFT_NUMERIC_FIELDS:
			with self.subTest(field=field), self.assertRaisesRegex(frappe.ValidationError, "angka tidak negatif"):
				shift[field] = -1
				try:
					self.validate()
				finally:
					shift[field] = 0

	def test_enabled_mode_requires_an_active_shift(self):
		self.outlet.enable_outlet_auto_shift = 1
		with self.assertRaisesRegex(frappe.ValidationError, "minimal satu shift aktif"):
			self.validate()
		self.add_shift(enabled=0)
		with self.assertRaisesRegex(frappe.ValidationError, "minimal satu shift aktif"):
			self.validate()

	def prepare_activation(self):
		self.add_shift()
		self.outlet.enable_outlet_auto_shift = 1
		self.outlet.outlet_auto_shift_effective_from = "2026-10-15 00:00:00"

	def test_enabled_mode_requires_active_outlet(self):
		self.prepare_activation()
		self.outlet.is_active = 0
		with self.assertRaisesRegex(frappe.ValidationError, "outlet aktif"):
			self.validate()

	def test_enabled_mode_does_not_require_holiday_list(self):
		self.prepare_activation()
		self.outlet.holiday_list = None
		self.validate()

	def test_enabled_mode_requires_effective_datetime(self):
		self.prepare_activation()
		self.outlet.outlet_auto_shift_effective_from = None
		with self.assertRaisesRegex(frappe.ValidationError, "Tanggal mulai"):
			self.validate()

	def test_activation_is_blocked_before_attendance_integration(self):
		self.prepare_activation()
		with patch("custom_hr.hrm.doctype.outlet.outlet.OUTLET_AUTO_SHIFT_READY", False), self.assertRaisesRegex(frappe.ValidationError, "belum dapat diaktifkan"):
			self.validate()
		self.assertIsInstance(self.outlet, Outlet)

	def test_valid_outlet_can_be_enabled_after_local_readiness_is_opened(self):
		self.prepare_activation()
		with patch("custom_hr.hrm.doctype.outlet.outlet.OUTLET_AUTO_SHIFT_READY", True):
			self.validate()


class TestOutletShiftSchema(unittest.TestCase):
	def tearDown(self):
		frappe.clear_messages()

	def test_fixture_names_are_unique_and_registered(self):
		fixtures = json.loads(
			Path(frappe.get_app_path("custom_hr", "fixtures", "custom_field.json")).read_text(encoding="utf-8")
		)
		self.assertEqual(len(fixtures), len({field["name"] for field in fixtures}))
		registered = {
			name
			for fixture in frappe.get_hooks("fixtures", app_name="custom_hr")
			if fixture.get("doctype") == "Custom Field"
			for name in fixture["filters"][0][2]
		}
		for doctype, fields in get_outlet_shift_custom_fields().items():
			self.assertEqual(len(fields), len(OUTLET_SHIFT_FIELDS[doctype]))
			for field in fields:
				with self.subTest(field=field["name"]):
					self.assertIn(field["name"], registered)
					self.assertEqual(field["name"], f"{doctype}-{field['fieldname']}")
					if field["fieldtype"] not in {"Section Break", "Column Break"}:
						self.assertEqual(field["read_only"], 1)
						self.assertEqual(field["no_copy"], 1)
						self.assertFalse(field.get("reqd"))

	def test_outlet_schema_defaults_do_not_enable_mode(self):
		definition = json.loads(
			Path(frappe.get_app_path("custom_hr", "hrm", "doctype", "outlet", "outlet.json")).read_text(encoding="utf-8")
		)
		fields = {field["fieldname"]: field for field in definition["fields"]}
		self.assertEqual(fields["enable_outlet_auto_shift"]["default"], "0")
		self.assertEqual(fields["enable_outlet_auto_shift"]["read_only"], 0)
		self.assertEqual(fields["outlet_auto_shift_effective_from"]["read_only"], 0)
		self.assertEqual(fields["shift_transition_minutes"]["default"], "30")
		self.assertEqual(fields["shift_transition_minutes"]["non_negative"], 1)
		self.assertFalse(fields["outlet_auto_shift_effective_from"].get("default"))

	def test_tolerance_labels_are_registered_without_renaming_native_fields(self):
		definitions = json.loads(
			Path(frappe.get_app_path("custom_hr", "fixtures", "property_setter.json")).read_text(encoding="utf-8")
		)
		registered = {
			name
			for fixture in frappe.get_hooks("fixtures", app_name="custom_hr")
			if fixture.get("doctype") == "Property Setter"
			for name in fixture["filters"][0][2]
		}
		labels = {definition["field_name"]: definition["value"] for definition in definitions if definition["property"] == "label"}
		self.assertEqual(labels, {"late_entry_grace_period": "Toleransi Terlambat", "early_exit_grace_period": "Toleransi Pulang Awal"})
		for definition in definitions:
			self.assertIn(definition["name"], registered)
			self.assertNotIn("grace", definition["value"].lower())

	def test_migration_rejects_other_apps_customization_before_ddl(self):
		self.assert_migration_conflict(
			frappe._dict(module="Other App", fieldtype="Select", options="\nOutlet")
		)

	def test_native_location_coordinate_precision_is_seven_decimals(self):
		definitions = json.loads(Path(frappe.get_app_path("custom_hr", "fixtures", "property_setter.json")).read_text(encoding="utf-8"))
		precision = {row["field_name"]: row["value"] for row in definitions if row["doc_type"] == "Shift Location" and row["property"] == "precision"}
		self.assertEqual(precision, {"latitude": "7", "longitude": "7"})
		from custom_hr.patches.shift_location_coordinate_precision import execute
		with patch("custom_hr.patches.shift_location_coordinate_precision.make_property_setter") as setter:
			execute()
		self.assertEqual(setter.call_count, 2)
		for fieldname in ("latitude", "longitude"):
			setter.assert_any_call("Shift Location", fieldname, "precision", "7", "Int")

	def test_migration_rejects_existing_type_change_before_ddl(self):
		self.assert_migration_conflict(frappe._dict(module="HRM", fieldtype="Data", options=""))

	def test_migration_rejects_existing_options_change_before_ddl(self):
		self.assert_migration_conflict(
			frappe._dict(module="HRM", fieldtype="Select", options="\nDifferent Source")
		)

	def assert_migration_conflict(self, existing):
		definitions = {"Employee Checkin": [{"fieldname": "attendance_source", "fieldtype": "Select", "options": "\nOutlet"}]}
		module = "custom_hr.patches.add_outlet_shift_fields"
		with (
			patch(f"{module}.get_outlet_shift_custom_fields", return_value=definitions),
			patch(f"{module}.frappe.get_meta"),
			patch(f"{module}.frappe.db.exists", return_value=True),
			patch(f"{module}.frappe.get_doc", return_value=existing),
			patch(f"{module}.frappe.reload_doc") as reload_doc,
			patch(f"{module}.create_custom_fields") as create_fields,
			self.assertRaisesRegex(frappe.ValidationError, "definisi berbeda"),
		):
			execute()
		reload_doc.assert_not_called()
		create_fields.assert_not_called()
