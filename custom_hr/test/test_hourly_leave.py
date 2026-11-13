"""Izin per jam: rounding, the one-day shape of the leave, and attendance left alone."""

import unittest
from unittest.mock import patch

import frappe

from custom_hr.overrides.attendance import CustomAttendance
from custom_hr.overrides.leave_application import CustomLeaveApplication
from custom_hr.services import hourly_leave as svc


def leave(**values):
	return frappe._dict(
		dict(leave_type="Izin per Jam", from_date="2026-10-14", to_date="2026-10-16", half_day=1, half_day_date="2026-10-15") | values
	)


class TestHourlyLeave(unittest.TestCase):
	def validate(self, doc, hourly=True):
		with patch.object(svc, "is_hourly", return_value=hourly):
			svc.validate_hourly_leave(doc)
		return doc

	def test_hours_round_to_the_nearest_half_hour(self):
		for hours, expected in ((10 / 60, 0), (15 / 60, 0.5), (70 / 60, 1), (75 / 60, 1.5), (100 / 60, 1.5), (4.5, 4.5)):
			self.assertEqual(svc.round_half_hour(hours), expected, hours)

	def test_an_hourly_leave_is_one_day_with_its_rounded_hours(self):
		doc = self.validate(leave(from_time="08:00:00", to_time="09:20:00"))
		self.assertEqual((doc.izin_per_jam, doc.jam_izin, doc.to_date, doc.half_day, doc.half_day_date), (1, 1.5, "2026-10-14", 0, None))

	def test_times_are_required_and_must_run_forward(self):
		for times in ({}, {"from_time": "10:00:00", "to_time": "09:00:00"}, {"from_time": "10:00:00", "to_time": "10:10:00"}):
			with self.subTest(times=times), self.assertRaises(frappe.ValidationError):
				self.validate(leave(**times))

	def test_a_day_leave_drops_any_times(self):
		doc = self.validate(leave(leave_type="Cuti", from_time="08:00:00", to_time="10:00:00", jam_izin=2), hourly=False)
		self.assertEqual((doc.izin_per_jam, doc.from_time, doc.to_time, doc.jam_izin), (0, None, None, 0))

	def test_attendance_is_left_alone_only_for_an_hourly_leave(self):
		for method in ("validate_attendance", "update_attendance", "cancel_attendance"):
			for hourly, calls in ((1, 0), (0, 1)):
				doc = CustomLeaveApplication.__new__(CustomLeaveApplication)
				doc.izin_per_jam = hourly
				with self.subTest(method=method, hourly=hourly), patch(f"hrms.hr.doctype.leave_application.leave_application.LeaveApplication.{method}") as native:
					getattr(doc, method)()
					self.assertEqual(native.call_count, calls)

	def test_an_hourly_leave_keeps_the_attendance_status_a_day_leave_does_not(self):
		def native(doc):
			doc.status, doc.leave_type, doc.leave_application = "On Leave", "X", "LAP-1"

		for hourly, expected in ((1, ("Present", None, None)), (0, ("On Leave", "X", "LAP-1"))):
			doc = CustomAttendance.__new__(CustomAttendance)
			doc.status, doc.leave_type, doc.leave_application = "Present", None, None
			with self.subTest(hourly=hourly), patch("hrms.hr.doctype.attendance.attendance.Attendance.check_leave_record", native), patch("frappe.db.get_value", return_value=hourly):
				doc.check_leave_record()
				self.assertEqual((doc.status, doc.leave_type, doc.leave_application), expected)

	def test_attendance_made_later_picks_up_the_hours_of_its_day(self):
		doc = frappe._dict(employee="EMP", attendance_date="2026-10-14")
		with patch.object(svc, "izin_hours", return_value=2) as hours:
			svc.fill_attendance_izin(doc)
		self.assertEqual(doc.jam_izin, 2)
		hours.assert_called_once_with("EMP", "2026-10-14", "2026-10-14")

	def test_approving_or_cancelling_marks_that_days_attendance(self):
		doc = leave(izin_per_jam=1, employee="EMP")
		with patch.object(svc, "izin_hours", return_value=1.5), patch("frappe.get_all", return_value=["ATT-1"]) as get_all, patch("frappe.db.set_value") as set_value:
			svc.stamp_attendance_izin(doc)
		self.assertEqual(get_all.call_args.kwargs["filters"]["attendance_date"], "2026-10-14")
		set_value.assert_called_once_with("Attendance", "ATT-1", "jam_izin", 1.5, update_modified=False)
		with patch("frappe.get_all") as get_all:
			svc.stamp_attendance_izin(leave(izin_per_jam=0))
		get_all.assert_not_called()

	def test_only_approved_submitted_hourly_leave_of_the_period_counts(self):
		with patch("frappe.get_all", return_value=[1.5, 2]) as get_all:
			self.assertEqual(svc.izin_hours("EMP", "2026-09-26", "2026-10-25"), 3.5)
		filters = get_all.call_args.kwargs["filters"]
		self.assertEqual((filters["docstatus"], filters["status"], filters["izin_per_jam"]), (1, "Approved", 1))
		self.assertEqual(filters["from_date"], ["between", ["2026-09-26", "2026-10-25"]])
