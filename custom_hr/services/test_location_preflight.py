"""Location preflight must reuse authoritative validators without saving logs."""

from unittest.mock import MagicMock
from datetime import datetime

import frappe

from custom_hr.api import checkin
from custom_hr.services.test_checkin_api import CheckinTestCase


class TestLocationPreflight(CheckinTestCase):
	def setUp(self):
		self.context = {
			"allowed": True, "next_action": "IN", "paired_checkin": None,
			"mode": "Outlet", "employee": "EMP", "outlet": "Original Outlet",
			"server_time": "2026-10-16 10:00:00", "message": "",
		}
		self.mock("custom_hr.api.checkin.get_checkin_context", return_value=self.context)
		self.setting = self.mock("frappe.db.get_single_value", return_value=1)
		self.probe = MagicMock()
		self.make_doc = self.mock("frappe.get_doc", return_value=self.probe)
		self.geofence = self.mock("custom_hr.services.outlet_geofence.validate_outlet_geofence", return_value=True)
		base = "hrms.hr.doctype.employee_checkin.employee_checkin.EmployeeCheckin."
		self.native_shift = self.mock(base + "fetch_shift")
		self.native_distance = self.mock(base + "validate_distance_from_shift_location")

	def test_valid_location_does_not_insert_or_save(self):
		self.assertEqual(checkin.validate_checkin_location(0, 110, "IN"), {"valid": True})
		self.geofence.assert_called_once_with(self.probe)
		self.probe.insert.assert_not_called()
		self.probe.save.assert_not_called()
		self.native_shift.assert_not_called()

	def test_out_uses_original_session_outlet(self):
		self.context.update(next_action="OUT", paired_checkin="IN-ORIGINAL")
		checkin.validate_checkin_location(-7, 110, "OUT", "IN-ORIGINAL")
		self.assertEqual(self.make_doc.call_args.args[0]["outlet_at_checkin"], "Original Outlet")

	def test_outside_radius_propagates_before_submission(self):
		self.geofence.side_effect = frappe.ValidationError("Outside radius")
		with self.assertRaisesRegex(frappe.ValidationError, "Outside radius"):
			checkin.validate_checkin_location(-7, 110, "IN")
		self.probe.insert.assert_not_called()

	def test_disabled_gps_does_not_require_coordinates(self):
		self.setting.return_value = 0
		self.assertTrue(checkin.validate_checkin_location(log_type="IN")["valid"])
		self.make_doc.assert_not_called()

	def test_changed_action_or_original_in_fails_closed(self):
		for action, expected in [("OUT", None), ("IN", "WRONG")]:
			with self.assertRaises(frappe.ValidationError):
				checkin.validate_checkin_location(-7, 110, action, expected)
		self.geofence.assert_not_called()

	def test_blocked_context_cannot_validate(self):
		self.context.update(allowed=False, message="Session expired")
		with self.assertRaisesRegex(frappe.ValidationError, "Session expired"):
			checkin.validate_checkin_location(-7, 110, "IN")
		self.geofence.assert_not_called()

	def test_native_mode_uses_native_geofence_without_session_preparation(self):
		self.context["mode"] = "Native"
		self.geofence.return_value = False
		checkin.validate_checkin_location(-7, 110, "IN")
		self.native_shift.assert_called_once_with(self.probe)
		self.native_distance.assert_called_once_with(self.probe)

	def test_native_assignment_date_filters_receive_datetime_not_timestamp_text(self):
		self.context["mode"] = "Native"
		self.geofence.return_value = False
		checkin.validate_checkin_location(-7, 110, "IN")
		self.assertEqual(self.make_doc.call_args.args[0]["time"], datetime(2026, 10, 16, 10))
