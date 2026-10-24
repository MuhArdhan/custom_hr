"""Outlet Shift validity dates: a dated shift takes priority over an undated one with the same start."""

import unittest
from datetime import date, time
from unittest.mock import patch

import frappe

from custom_hr.hrm.doctype.outlet.outlet import Outlet
from custom_hr.services.outlet_shift import active_shift_names

STARTS = {"Pagi": time(7), "Pagi Khusus": time(7), "Siang": time(15)}


def row(shift_type, enabled=1, valid_from=None, valid_to=None):
	return frappe._dict(shift_type=shift_type, enabled=enabled, valid_from=valid_from, valid_to=valid_to)


class TestActiveShiftNames(unittest.TestCase):
	day = date(2026, 11, 10)

	def names(self, *rows, day=None):
		return sorted(active_shift_names(rows, STARTS, day or self.day))

	def test_rows_without_dates_are_always_active(self):
		self.assertEqual(self.names(row("Pagi"), row("Siang")), ["Pagi", "Siang"])

	def test_disabled_rows_are_ignored(self):
		self.assertEqual(self.names(row("Pagi", enabled=0), row("Siang")), ["Siang"])

	def test_row_is_active_only_inside_its_dates_inclusive(self):
		temp = row("Siang", valid_from="2026-11-10", valid_to="2026-11-12")
		self.assertEqual(self.names(temp, day=date(2026, 11, 9)), [])
		self.assertEqual(self.names(temp, day=date(2026, 11, 10)), ["Siang"])
		self.assertEqual(self.names(temp, day=date(2026, 11, 12)), ["Siang"])
		self.assertEqual(self.names(temp, day=date(2026, 11, 13)), [])

	def test_empty_end_date_never_expires(self):
		self.assertEqual(self.names(row("Siang", valid_from="2026-11-01"), day=date(2030, 1, 1)), ["Siang"])

	def test_dated_shift_takes_priority_over_the_undated_one_with_the_same_start(self):
		temp = row("Pagi Khusus", valid_from="2026-11-10", valid_to="2026-11-12")
		self.assertEqual(self.names(row("Pagi"), row("Siang"), temp), ["Pagi Khusus", "Siang"])

	def test_undated_shift_returns_outside_the_dated_period(self):
		temp = row("Pagi Khusus", valid_from="2026-11-01", valid_to="2026-11-05")
		self.assertEqual(self.names(row("Pagi"), temp), ["Pagi"])

	def test_open_ended_dated_shift_keeps_priority_forever(self):
		temp = row("Pagi Khusus", valid_from="2026-11-01")
		self.assertEqual(self.names(row("Pagi"), temp, day=date(2030, 1, 1)), ["Pagi Khusus"])


class TestOutletShiftValidation(unittest.TestCase):
	def validate(self, *rows):
		outlet = Outlet({"doctype": "Outlet", "enable_outlet_auto_shift": 0})
		outlet.shifts = list(rows)
		shifts = [
			frappe._dict(name=name, start_time=start, end_time=time(23), **{f: 0 for f in (
				"begin_check_in_before_shift_start_time", "allow_check_out_after_shift_end_time", "late_entry_grace_period",
				"early_exit_grace_period", "working_hours_threshold_for_half_day", "working_hours_threshold_for_absent")})
			for name, start in STARTS.items()
		]
		with patch("frappe.get_all", return_value=shifts):
			outlet.validate_shifts()

	def refused(self, *rows):
		with self.assertRaises(frappe.ValidationError):
			self.validate(*rows)

	def test_dated_shift_may_share_a_start_with_an_undated_one(self):
		self.validate(row("Pagi"), row("Pagi Khusus", valid_from="2026-11-01", valid_to="2026-11-05"))

	def test_two_undated_shifts_with_the_same_start_are_refused(self):
		self.refused(row("Pagi"), row("Pagi Khusus"))

	def test_dated_shifts_with_the_same_start_and_overlapping_dates_are_refused(self):
		self.refused(
			row("Pagi", valid_from="2026-11-01", valid_to="2026-11-10"),
			row("Pagi Khusus", valid_from="2026-11-10", valid_to="2026-11-20"),
		)

	def test_same_start_date_is_refused_even_without_end_dates(self):
		self.refused(row("Pagi", valid_from="2026-11-01"), row("Pagi Khusus", valid_from="2026-11-01"))

	def test_back_to_back_dated_shifts_with_the_same_start_are_allowed(self):
		self.validate(
			row("Pagi", valid_from="2026-11-01", valid_to="2026-11-09"),
			row("Pagi Khusus", valid_from="2026-11-10", valid_to="2026-11-20"),
		)

	def test_different_starts_may_overlap_in_dates(self):
		self.validate(row("Pagi", valid_from="2026-11-01"), row("Siang", valid_from="2026-11-01"))

	def test_disabled_rows_do_not_clash(self):
		self.validate(row("Pagi"), row("Pagi Khusus", enabled=0))

	def test_end_before_start_is_refused(self):
		self.refused(row("Siang", valid_from="2026-11-10", valid_to="2026-11-01"))


class TestAutoShiftDefaults(unittest.TestCase):
	def outlet(self, **values):
		return Outlet({"doctype": "Outlet", "is_active": 1, "shift_transition_minutes": 30, **values})

	def test_enabling_without_a_start_time_stamps_it_instead_of_asking(self):
		outlet = self.outlet(enable_outlet_auto_shift=1)
		outlet.validate_auto_shift_activation()
		self.assertTrue(outlet.outlet_auto_shift_effective_from)

	def test_an_existing_start_time_is_kept(self):
		outlet = self.outlet(enable_outlet_auto_shift=1, outlet_auto_shift_effective_from="2026-10-15 00:00:00")
		outlet.validate_auto_shift_activation()
		self.assertEqual(str(outlet.outlet_auto_shift_effective_from), "2026-10-15 00:00:00")

	def test_outlet_without_shifts_can_be_saved_with_auto_shift_on(self):
		self.outlet(enable_outlet_auto_shift=1).validate_shifts()
