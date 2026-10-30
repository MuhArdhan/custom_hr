# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""T10 coordinate/radius rules and lifecycle protection; no persistent writes."""

import json
import unittest
from unittest.mock import patch

import frappe

from hrms.hr.doctype.employee_checkin.employee_checkin import CheckinRadiusExceededError
from custom_hr.overrides.employee_checkin import CustomEmployeeCheckin
from custom_hr.services import outlet_geofence as service

MODULE = "custom_hr.services.outlet_geofence"


def outlet(**changes):
	row = frappe._dict(name="Original Outlet", shift_location="Original Location", latitude=-7.0, longitude=110.0, checkin_radius=100)
	row.update(changes)
	return row


class TestCase(unittest.TestCase):
	def mock(self, target, **kwargs):
		p = patch(target, **kwargs)
		self.addCleanup(p.stop)
		return p.start()

	def tearDown(self):
		frappe.clear_messages()


class TestCoordinatesAndRadius(TestCase):
	def test_numeric_strings_are_parsed(self):
		self.assertEqual(service.coordinates("-7", "110"), (-7, 110))

	def test_zero_is_valid_on_one_axis(self):
		self.assertEqual(service.coordinates(0, 110), (0, 110))
		self.assertEqual(service.coordinates(-7, 0), (-7, 0))

	def test_coordinate_range_endpoints_are_valid(self):
		self.assertEqual(service.coordinates(90, 180), (90, 180))
		self.assertEqual(service.coordinates(-90, -180), (-90, -180))

	def test_missing_and_default_zero_pair_are_not_valid_gps(self):
		for pair in ((None, 110), (-7, None), ("", 110), (-7, "  "), (0, 0), (False, 110), (-7, True)):
			with self.subTest(pair=pair), self.assertRaises(ValueError):
				service.coordinates(*pair)

	def test_nonfinite_nonnumeric_and_out_of_range_coordinates_are_rejected(self):
		for pair in (("invalid", 110), (-7, "Infinity"), (float("nan"), 110), (91, 110), (-91, 110), (-7, 181), (-7, -181), ({}, 110)):
			with self.subTest(pair=pair), self.assertRaises(ValueError):
				service.coordinates(*pair)

	def test_at_outlet_center_has_zero_distance(self):
		self.assertEqual(service.check_position(outlet(), -7, 110), 0)

	def test_real_nearby_and_distant_coordinates(self):
		self.assertLess(service.check_position(outlet(), -7.0001, 110), 100)
		with self.assertRaises(CheckinRadiusExceededError):
			service.check_position(outlet(), -7.01, 110)

	def test_inside_exact_boundary_and_outside_radius(self):
		for distance, accepted in ((99.999, True), (100, True), (100.001, False)):
			with self.subTest(distance=distance), patch(f"{MODULE}.get_distance_between_coordinates", return_value=distance):
				if accepted:
					self.assertEqual(service.check_position(outlet(), -7, 110), distance)
				else:
					with self.assertRaises(CheckinRadiusExceededError):
						service.check_position(outlet(), -7, 110)

	def test_radius_comes_from_configuration_not_a_fixed_buffer(self):
		with patch(f"{MODULE}.get_distance_between_coordinates", return_value=150):
			self.assertEqual(service.check_position(outlet(checkin_radius=200), -7, 110), 150)
			with self.assertRaises(CheckinRadiusExceededError):
				service.check_position(outlet(checkin_radius=149), -7, 110)

	def test_missing_negative_fractional_and_nonfinite_radius_are_configuration_errors(self):
		for radius in (None, "", -1, 0.5, float("nan"), float("inf"), "bad", True):
			with self.subTest(radius=radius), self.assertRaisesRegex(frappe.ValidationError, "Konfigurasi lokasi Outlet"):
				service.check_position(outlet(checkin_radius=radius), -7, 110)

	def test_native_zero_radius_records_valid_gps_without_distance_limit(self):
		with patch(f"{MODULE}.get_distance_between_coordinates") as distance:
			self.assertIsNone(service.check_position(outlet(checkin_radius=0), 40, -70))
			distance.assert_not_called()
		with self.assertRaisesRegex(frappe.ValidationError, "GPS tidak tersedia"):
			service.check_position(outlet(checkin_radius=0), None, None)

	def test_incomplete_outlet_coordinates_are_configuration_errors_not_assignment_fallback(self):
		for changes in ({"latitude": None}, {"longitude": None}, {"latitude": 0, "longitude": 0}, {"latitude": float("nan")}, {"longitude": 181}):
			with self.subTest(changes=changes), self.assertRaisesRegex(frappe.ValidationError, "Konfigurasi lokasi Outlet"):
				service.check_position(outlet(**changes), -7, 110)

	def test_missing_gps_has_clear_error_and_does_not_compute_distance(self):
		with patch(f"{MODULE}.get_distance_between_coordinates") as distance:
			with self.assertRaisesRegex(frappe.ValidationError, "GPS tidak tersedia"):
				service.check_position(outlet(), None, None)
		distance.assert_not_called()

	def test_invalid_distance_calculation_fails_closed(self):
		with patch(f"{MODULE}.get_distance_between_coordinates", side_effect=ValueError("domain")):
			with self.assertRaisesRegex(frappe.ValidationError, "Jarak GPS"):
				service.check_position(outlet(), -7, 110)
		with patch(f"{MODULE}.get_distance_between_coordinates", return_value=float("nan")):
			with self.assertRaises(CheckinRadiusExceededError):
				service.check_position(outlet(), -7, 110)


class TestGeofenceLifecycle(TestCase):
	def setUp(self):
		self.doc = frappe.get_doc({
			"doctype": "Employee Checkin", "employee": "EMP", "log_type": "IN", "time": "2026-10-15 05:04:00",
			"attendance_source": "Outlet", "outlet_at_checkin": "Original Outlet", "latitude": -7, "longitude": 110,
		})
		self.config = outlet()
		self.setting = self.mock("frappe.db.get_single_value", return_value=1)
		self.reader = self.mock("frappe.db.get_value", side_effect=self.read_outlet)

	def read_outlet(self, dt, name, fields, **kwargs):
		self.assertIn(dt, ("Outlet", "Shift Location"))
		self.assertEqual(name, "Original Outlet" if dt == "Outlet" else "Original Location")
		self.assertTrue(kwargs["for_update"])
		return self.config.copy() if self.config else None

	def test_in_and_out_both_use_original_outlet_with_no_assignments(self):
		with patch("frappe.get_all", side_effect=AssertionError("No Shift Assignment lookup")):
			for log_type in ("IN", "OUT"):
				self.doc.log_type = log_type
				self.assertTrue(service.validate_outlet_geofence(self.doc))
		self.assertEqual(self.reader.call_count, 4)

	def test_out_does_not_look_up_current_employee_outlet_or_company(self):
		self.doc.log_type = "OUT"
		self.doc.paired_checkin = "PERSISTED-IN"
		service.validate_outlet_geofence(self.doc)
		self.assertEqual([call.args[0] for call in self.reader.call_args_list], ["Outlet", "Shift Location"])

	def test_out_reads_current_radius_of_original_outlet(self):
		self.doc.log_type = "OUT"
		with patch(f"{MODULE}.get_distance_between_coordinates", return_value=50):
			service.validate_outlet_geofence(self.doc)
			self.config.checkin_radius = 40
			with self.assertRaises(CheckinRadiusExceededError):
				service.validate_outlet_geofence(self.doc)

	def test_disabled_geolocation_does_not_require_gps_or_valid_outlet_config(self):
		self.setting.return_value = 0
		self.doc.latitude = self.doc.longitude = None
		self.assertTrue(service.validate_outlet_geofence(self.doc))
		self.reader.assert_not_called()

	def test_native_source_is_not_claimed_by_outlet_geofence(self):
		self.doc.attendance_source = None
		self.assertFalse(service.validate_outlet_geofence(self.doc))
		self.setting.assert_not_called()
		self.reader.assert_not_called()

	def test_missing_original_outlet_has_clear_error(self):
		self.config = None
		with self.assertRaisesRegex(frappe.ValidationError, "Outlet asal sesi tidak ditemukan"):
			service.validate_outlet_geofence(self.doc)

	def test_blank_outlet_never_falls_back_to_company_or_assignment(self):
		self.doc.outlet_at_checkin = None
		with self.assertRaisesRegex(frappe.ValidationError, "Outlet asal sesi tidak ditemukan"):
			service.validate_outlet_geofence(self.doc)
		self.reader.assert_not_called()

	def test_missing_link_records_gps_without_a_radius_check(self):
		self.config.shift_location = None
		self.doc.latitude, self.doc.longitude = 40, -70  # far from the legacy outlet coordinates
		self.assertTrue(service.validate_outlet_geofence(self.doc))
		self.assertEqual((self.doc.latitude, self.doc.longitude), (40, -70))
		self.assertEqual(self.reader.call_count, 1)

	def test_location_without_coordinates_records_gps_without_a_radius_check(self):
		self.config.latitude = self.config.longitude = 0
		self.doc.latitude, self.doc.longitude = 40, -70
		self.assertTrue(service.validate_outlet_geofence(self.doc))
		self.assertEqual((self.doc.latitude, self.doc.longitude), (40, -70))

	def test_missing_link_still_requires_gps(self):
		self.config.shift_location = None
		self.doc.latitude = self.doc.longitude = None
		with self.assertRaisesRegex(frappe.ValidationError, "GPS tidak tersedia"):
			service.validate_outlet_geofence(self.doc)

	def test_deleted_link_target_does_not_fall_back_to_legacy_radius(self):
		self.reader.side_effect = [self.config, None]
		with self.assertRaisesRegex(frappe.ValidationError, "Shift Location belum dihubungkan"):
			service.validate_outlet_geofence(self.doc)

	def test_unlinked_outlet_values_are_not_runtime_sources(self):
		self.reader.side_effect = [outlet(latitude=80, longitude=80, checkin_radius=1), outlet()]
		self.assertTrue(service.validate_outlet_geofence(self.doc))

	def test_existing_log_is_not_revalidated_against_changed_master(self):
		self.doc.name = "STORED"
		self.doc.set("__islocal", 0)
		self.doc.latitude = self.doc.longitude = None
		self.assertTrue(service.validate_outlet_geofence(self.doc))
		self.setting.assert_not_called()
		self.reader.assert_not_called()

	def test_gps_is_normalized_to_actual_checkin_field_precision(self):
		self.config.latitude, self.config.longitude = -7.1234567, 110.7654321
		self.doc.latitude, self.doc.longitude = "-7.12345674", "110.76543214"
		service.validate_outlet_geofence(self.doc)
		self.assertEqual(self.doc.latitude, -7.1234567)
		self.assertEqual(self.doc.longitude, 110.7654321)

	def test_invalid_gps_string_is_not_silently_coerced_to_zero(self):
		self.config.latitude = 0
		self.doc.latitude = "not-a-number"
		with self.assertRaisesRegex(frappe.ValidationError, "GPS tidak tersedia"):
			service.validate_outlet_geofence(self.doc)

	def test_location_payload_cannot_replace_configured_radius(self):
		self.doc.geofence_radius_m = 999999
		self.doc.shift_policy_snapshot = {"latitude": -7.01, "longitude": 110, "geofence_radius_m": 999999}
		self.doc.latitude = -7.01
		with self.assertRaises(CheckinRadiusExceededError):
			service.validate_outlet_geofence(self.doc)

	def test_native_controller_keeps_original_assignment_validation(self):
		self.doc.attendance_source = None
		with patch("hrms.hr.doctype.employee_checkin.employee_checkin.EmployeeCheckin.validate_distance_from_shift_location") as native:
			self.doc.validate_distance_from_shift_location()
		native.assert_called_once()

	def test_outlet_controller_never_uses_native_assignment_validation(self):
		with patch("hrms.hr.doctype.employee_checkin.employee_checkin.EmployeeCheckin.validate_distance_from_shift_location") as native:
			self.doc.validate_distance_from_shift_location()
		native.assert_not_called()

	def test_optional_outlet_geolocation_does_not_fall_through_to_native(self):
		self.setting.return_value = 0
		with patch("hrms.hr.doctype.employee_checkin.employee_checkin.EmployeeCheckin.validate_distance_from_shift_location") as native:
			self.doc.validate_distance_from_shift_location()
		native.assert_not_called()

	def test_before_validate_enforces_geofence_even_for_hr_and_ignore_flags(self):
		self.doc.latitude = -7.01
		self.doc.flags.ignore_validate = self.doc.flags.ignore_checkin_restrictions = True
		with patch("custom_hr.overrides.employee_checkin.prepare_or_protect_checkin", return_value=True):
			with self.assertRaises(CheckinRadiusExceededError):
				self.doc.before_validate()

	def test_before_validate_populates_location_even_when_validate_is_skipped(self):
		self.doc.flags.ignore_validate = True
		with patch("custom_hr.overrides.employee_checkin.prepare_or_protect_checkin", return_value=True):
			self.doc.before_validate()
		self.assertEqual(json.loads(self.doc.geolocation)["features"][0]["geometry"]["coordinates"], [110, -7])

	def test_native_geolocation_storage_behavior_is_unchanged(self):
		self.doc.attendance_source = None
		self.doc.latitude = 0
		self.doc.set_geolocation()
		self.assertFalse(self.doc.get("geolocation"))

	def test_outlet_map_preserves_zero_axis_and_numeric_values(self):
		self.doc.latitude, self.doc.longitude = "0", "110"
		self.doc.set_geolocation()
		self.assertEqual(json.loads(self.doc.geolocation)["features"][0]["geometry"]["coordinates"], [110, 0])

	def test_missing_optional_gps_does_not_create_zero_zero_map(self):
		self.doc.latitude = self.doc.longitude = 0
		self.doc.set_geolocation()
		self.assertFalse(self.doc.get("geolocation"))

	def test_face_verification_is_still_enforced_before_geofence_for_self_service(self):
		from custom_hr.services.outlet_checkin import _validate_outlet_self_service
		with patch("custom_hr.services.outlet_checkin.is_hr_operator", return_value=False), patch.object(CustomEmployeeCheckin, "validate_self_service_time"), patch.object(CustomEmployeeCheckin, "validate_face_verification", side_effect=frappe.ValidationError("Face required")) as face:
			with self.assertRaisesRegex(frappe.ValidationError, "Face required"):
				_validate_outlet_self_service(self.doc)
		face.assert_called_once()


class TestAbsenceGeofenceSafety(TestCase):
	def test_invalid_outlet_location_blocks_automatic_no_log_absence(self):
		from custom_hr.services.outlet_scheduler import _day_context
		from custom_hr.services.test_outlet_scheduler import stable_records

		employee, config = stable_records()
		config.shift_location = "Linked Location"
		config.latitude, config.longitude, config.checkin_radius = 100, 110, 50  # latitude out of range
		with patch("custom_hr.hrm.doctype.outlet.outlet.OUTLET_AUTO_SHIFT_READY", True), patch("frappe.db.get_single_value", return_value=1), patch("frappe.db.get_value", side_effect=lambda dt, *a, **k: employee if dt == "Employee" else config):
			with self.assertRaisesRegex(frappe.ValidationError, "Konfigurasi lokasi Outlet"):
				_day_context("EMP", "2026-10-15")

	def test_disabled_geolocation_does_not_add_absence_configuration_requirement(self):
		from custom_hr.services.outlet_scheduler import _day_context
		from custom_hr.services.test_outlet_scheduler import stable_records

		employee, config = stable_records()
		with patch("custom_hr.hrm.doctype.outlet.outlet.OUTLET_AUTO_SHIFT_READY", True), patch("frappe.db.get_single_value", return_value=0), patch("frappe.db.get_value", side_effect=lambda dt, *a, **k: employee if dt == "Employee" else config), patch("custom_hr.services.outlet_scheduler.read_outlet_geofence") as geo, patch("custom_hr.services.outlet_scheduler.resolve_outlet_shift", side_effect=frappe.ValidationError("schedule stub")):
			with self.assertRaisesRegex(frappe.ValidationError, "schedule stub"):
				_day_context("EMP", "2026-10-15")
		geo.assert_not_called()
