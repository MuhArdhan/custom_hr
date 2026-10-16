"""Gallery modal reads outlet/shift from the saved punch, not current masters."""

import unittest
from unittest.mock import patch

import frappe

from custom_hr import api


class TestGalleryShift(unittest.TestCase):
	def log(self, **values):
		return frappe._dict(
			name="LOG", employee="EMP", log_type="IN", time="2026-10-15 10:00:00",
			**values,
		)

	def test_gallery_returns_saved_outlet_and_shift(self):
		log = self.log(outlet_at_checkin="Original Outlet", shift="Shift 2")
		with patch.object(api, "_require_employee_gallery_access"), patch.object(api, "_get_accessible_employees", return_value=["EMP"]), patch("frappe.get_all", side_effect=[[log], [], []]) as query:
			result = api.get_employee_checkin_gallery(from_date="2026-10-15", to_date="2026-10-15")
		self.assertEqual(result["rows"][0].outlet_at_checkin, "Original Outlet")
		self.assertEqual(result["rows"][0].shift, "Shift 2")
		self.assertTrue({"outlet_at_checkin", "shift"}.issubset(query.call_args_list[0].kwargs["fields"]))

	def test_daily_modal_receives_same_saved_fields(self):
		log = self.log(outlet_at_checkin="Original Outlet", shift="Shift 1")
		with patch.object(api, "_require_employee_gallery_access"), patch("frappe.has_permission"), patch("frappe.get_all", side_effect=[[log], []]) as query, patch("frappe.db.get_value", return_value=frappe._dict(employee_name="Test")):
			result = api.get_attendance_daily_cards("EMP", "2026-10-15", "2026-10-15")
		self.assertEqual(result["days"][0]["logs"][0].shift, "Shift 1")
		self.assertEqual(result["days"][0]["logs"][0].outlet_at_checkin, "Original Outlet")
		self.assertTrue({"outlet_at_checkin", "shift"}.issubset(query.call_args_list[0].kwargs["fields"]))

	def test_legacy_logs_keep_empty_metadata_without_guessing_outlet(self):
		log = self.log(outlet_at_checkin=None, shift=None)
		with patch.object(api, "_require_employee_gallery_access"), patch.object(api, "_get_accessible_employees", return_value=["EMP"]), patch("frappe.get_all", side_effect=[[log], [], []]):
			result = api.get_employee_checkin_gallery(from_date="2026-10-15", to_date="2026-10-15")
		self.assertIsNone(result["rows"][0].outlet_at_checkin)
		self.assertIsNone(result["rows"][0].shift)
