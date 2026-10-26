"""Attendance shows working time, late entry and early exit as hours and minutes."""

import unittest
from datetime import timedelta
from unittest.mock import patch

import frappe

from custom_hr.services import attendance_duration as svc


def attendance(**values):
	defaults = dict(shift="Pagi", attendance_date="2026-10-26", working_hours=0, late_entry=0, early_exit=0, in_time=None, out_time=None)
	return frappe._dict(defaults | values)


def shift(start, end):
	hm = lambda text: timedelta(hours=int(text[:2]), minutes=int(text[3:]))
	return patch("frappe.db.get_value", return_value=(hm(start), hm(end)))


class TestAttendanceDuration(unittest.TestCase):
	def test_format(self):
		self.assertEqual(svc.format_duration(0), "0 min")
		self.assertEqual(svc.format_duration(45), "45 min")
		self.assertEqual(svc.format_duration(120), "2 hr")
		self.assertEqual(svc.format_duration(453), "7 hr 33 min")

	def test_working_hours_become_hours_and_minutes(self):
		doc = attendance(working_hours=7.55)
		with shift("08:00", "16:00"):
			svc.fill_durations(doc)
		self.assertEqual(doc.working_duration, "7 hr 33 min")

	def test_late_entry_is_measured_from_the_shift_start(self):
		doc = attendance(late_entry=1, in_time="2026-10-26 09:05:00")
		with shift("08:00", "16:00"):
			svc.fill_durations(doc)
		self.assertEqual(doc.late_entry_duration, "1 hr 5 min")

	def test_early_exit_is_measured_to_the_shift_end(self):
		doc = attendance(early_exit=1, out_time="2026-10-26 15:20:00")
		with shift("08:00", "16:00"):
			svc.fill_durations(doc)
		self.assertEqual(doc.early_exit_duration, "40 min")

	def test_overnight_shift_ends_the_next_day(self):
		doc = attendance(early_exit=1, out_time="2026-10-27 05:30:00")
		with shift("22:00", "06:00"):
			svc.fill_durations(doc)
		self.assertEqual(doc.early_exit_duration, "30 min")

	def test_unflagged_or_unshifted_rows_have_no_late_or_early_text(self):
		doc = attendance(in_time="2026-10-26 09:05:00", out_time="2026-10-26 15:20:00")
		with shift("08:00", "16:00"):
			svc.fill_durations(doc)
		self.assertEqual((doc.late_entry_duration, doc.early_exit_duration), ("", ""))

	def test_a_very_short_visit_shows_zero_minutes_instead_of_nothing(self):
		doc = attendance(working_hours=0, in_time="2026-10-26 14:03:43", out_time="2026-10-26 14:03:48")
		svc.fill_durations(doc)
		self.assertEqual(doc.working_duration, "0 min")

	def test_missing_out_time_leaves_the_duration_empty(self):
		doc = attendance(working_hours=0, in_time="2026-10-26 14:03:43")
		svc.fill_durations(doc)
		self.assertEqual(doc.working_duration, "")
		doc = attendance(late_entry=1, in_time="2026-10-26 09:05:00", shift=None)
		svc.fill_durations(doc)
		self.assertEqual(doc.late_entry_duration, "")
