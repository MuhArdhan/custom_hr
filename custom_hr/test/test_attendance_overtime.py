"""Unit tests for two-way sync of approved Overtime Requests onto Attendance."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from custom_hr.services import attendance_overtime as svc


class TestAttendanceOvertime(unittest.TestCase):
	def test_fill_attendance_overtime_overrides_shift_marker_with_approved_type(self):
		att = frappe._dict(
			employee="EMP-1",
			attendance_date="2026-10-20",
			actual_overtime_duration=3.0,
			overtime_type="Lembur",
		)
		planned = {("EMP-1", frappe.utils.getdate("2026-10-20")): frappe._dict(request="LEMBUR-1", hours=2.0, overtime_type="Holiday")}
		with patch.object(svc, "approved_overtime_requests", return_value=planned):
			svc.fill_attendance_overtime(att)

		self.assertEqual(att.overtime_request, "LEMBUR-1")
		self.assertEqual(att.overtime_type, "Holiday")
		self.assertEqual(att.approved_overtime_hours, 2.0)
		self.assertEqual(att.paid_overtime_hours, 2.0)

	def test_fill_attendance_overtime_uses_actual_when_smaller_or_zero(self):
		planned = {("EMP-1", frappe.utils.getdate("2026-10-20")): frappe._dict(request="LEMBUR-1", hours=2.0, overtime_type="Lembur")}

		att_partial = frappe._dict(employee="EMP-1", attendance_date="2026-10-20", actual_overtime_duration=1.5)
		with patch.object(svc, "approved_overtime_requests", return_value=planned):
			svc.fill_attendance_overtime(att_partial)
		self.assertEqual((att_partial.approved_overtime_hours, att_partial.paid_overtime_hours), (2.0, 1.5))

		att_zero = frappe._dict(employee="EMP-1", attendance_date="2026-10-20", actual_overtime_duration=0.0)
		with patch.object(svc, "approved_overtime_requests", return_value=planned):
			svc.fill_attendance_overtime(att_zero)
		self.assertEqual((att_zero.overtime_request, att_zero.overtime_type, att_zero.approved_overtime_hours, att_zero.paid_overtime_hours), ("LEMBUR-1", "Lembur", 2.0, 0.0))

		# Without an approved Overtime Request, overtime_type is cleared even if actual_overtime_duration > 0
		unapproved = frappe._dict(
			employee="EMP-1",
			attendance_date="2026-10-21",
			actual_overtime_duration=2.0,
			overtime_type="Lembur",
		)
		with patch.object(svc, "approved_overtime_requests", return_value={}):
			svc.fill_attendance_overtime(unapproved)
		self.assertIsNone(unapproved.overtime_type)
		self.assertIsNone(unapproved.overtime_request)
		self.assertEqual((unapproved.approved_overtime_hours, unapproved.paid_overtime_hours), (0.0, 0.0))

	def test_stamp_employee_date_updates_submitted_attendance_and_clears_when_removed(self):
		day = frappe.utils.getdate("2026-10-20")
		existing = [
			frappe._dict(
				name="HR-ATT-1",
				actual_overtime_duration=1.5,
				overtime_type="Lembur",
				overtime_request=None,
				approved_overtime_hours=0.0,
				paid_overtime_hours=0.0,
			)
		]
		planned = {("EMP-1", day): frappe._dict(request="LEMBUR-1", hours=2.0, overtime_type="Holiday")}
		with (
			patch("frappe.get_all", return_value=existing),
			patch.object(svc, "approved_overtime_requests", return_value=planned),
			patch("frappe.db.set_value") as set_val,
		):
			svc.stamp_employee_date("EMP-1", "2026-10-20")

		set_val.assert_called_once_with(
			"Attendance",
			"HR-ATT-1",
			{"overtime_request": "LEMBUR-1", "overtime_type": "Holiday", "approved_overtime_hours": 2.0, "paid_overtime_hours": 1.5},
			update_modified=False,
		)

		# Re-running with matching values is a no-op
		same = [
			frappe._dict(
				name="HR-ATT-1",
				actual_overtime_duration=1.5,
				overtime_type="Holiday",
				overtime_request="LEMBUR-1",
				approved_overtime_hours=2.0,
				paid_overtime_hours=1.5,
			)
		]
		with (
			patch("frappe.get_all", return_value=same),
			patch.object(svc, "approved_overtime_requests", return_value=planned),
			patch("frappe.db.set_value") as set_val,
		):
			svc.stamp_employee_date("EMP-1", "2026-10-20")
		set_val.assert_not_called()

		# When the approved request is deleted/rejected, overtime_type clears to None
		with (
			patch("frappe.get_all", return_value=same),
			patch.object(svc, "approved_overtime_requests", return_value={}),
			patch("frappe.db.set_value") as set_val,
		):
			svc.stamp_employee_date("EMP-1", "2026-10-20", exclude_request="LEMBUR-1")
		set_val.assert_called_once_with(
			"Attendance",
			"HR-ATT-1",
			{"overtime_request": None, "overtime_type": None, "approved_overtime_hours": 0.0, "paid_overtime_hours": 0.0},
			update_modified=False,
		)

	def test_clear_request_attendances_excludes_deleted_request(self):
		doc = frappe._dict(name="LEMBUR-1", date="2026-10-20", employees=[frappe._dict(employee="EMP-1")])
		with patch.object(svc, "stamp_employee_date") as stamp:
			svc.clear_request_attendances(doc)
		stamp.assert_called_once_with("EMP-1", "2026-10-20", exclude_request="LEMBUR-1")
