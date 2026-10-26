"""Outlet Shift rows: weekdays decide which shifts apply on a day; same-start shifts are allowed."""

import unittest
from datetime import date, time, timedelta
from unittest.mock import patch

import frappe

from custom_hr.api import roster
from custom_hr.hrm.doctype.outlet.outlet import Outlet
from custom_hr.services.outlet_shift import active_shift_names, applies_on, row_weekdays

STARTS = {"Pagi": time(7), "Pagi Khusus": time(7), "Siang": time(15), "Pagi Senin-Kamis": time(6), "Pagi Jumat": time(6)}
MON_THU, FRI = {"monday": 1, "tuesday": 1, "wednesday": 1, "thursday": 1}, {"friday": 1}
MONDAY, FRIDAY = date(2026, 11, 9), date(2026, 11, 13)


def row(shift_type, enabled=1, **days):
	return frappe._dict(shift_type=shift_type, enabled=enabled, **days)


class TestActiveShiftNames(unittest.TestCase):
	day = date(2026, 11, 10)

	def names(self, *rows, day=None):
		return sorted(active_shift_names(rows, day or self.day))

	def test_enabled_rows_are_always_active(self):
		self.assertEqual(self.names(row("Pagi"), row("Siang")), ["Pagi", "Siang"])

	def test_disabled_rows_are_ignored(self):
		self.assertEqual(self.names(row("Pagi", enabled=0), row("Siang")), ["Siang"])

	def test_same_start_shifts_are_both_active_on_the_day(self):
		self.assertEqual(self.names(row("Pagi"), row("Pagi Khusus")), ["Pagi", "Pagi Khusus"])

	def test_row_without_weekdays_applies_every_day(self):
		self.assertEqual(row_weekdays(row("Pagi")), frozenset(range(7)))
		self.assertTrue(all(applies_on(row("Pagi"), MONDAY + timedelta(days=offset)) for offset in range(7)))

	def test_weekday_row_only_applies_on_its_days(self):
		pagi = row("Pagi", **MON_THU)
		self.assertEqual(row_weekdays(pagi), frozenset({0, 1, 2, 3}))
		self.assertEqual(self.names(pagi, day=MONDAY), ["Pagi"])
		self.assertEqual(self.names(pagi, day=FRIDAY), [])

	def test_op_pagi_table_resolves_per_weekday(self):
		table = (row("Pagi Senin-Kamis", **MON_THU), row("Pagi Jumat", **FRI))
		self.assertEqual(self.names(*table, day=MONDAY), ["Pagi Senin-Kamis"])
		self.assertEqual(self.names(*table, day=FRIDAY), ["Pagi Jumat"])


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

	def test_same_start_rows_are_accepted(self):
		self.validate(row("Pagi"), row("Pagi Khusus"))

	def test_same_start_shifts_on_different_weekdays_are_allowed(self):
		self.validate(row("Pagi Senin-Kamis", **MON_THU), row("Pagi Jumat", **FRI))

	def test_disabled_rows_are_accepted(self):
		self.validate(row("Pagi"), row("Pagi Khusus", enabled=0))

	def test_validate_shifts_still_rejects_duplicate_shift_type(self):
		self.refused(row("Pagi"), row("Pagi"))

	def test_shift_type_is_required(self):
		self.refused(row(None))


class TestRosterShiftOptions(unittest.TestCase):
	def test_roster_options_do_not_skip_any_enabled_shift(self):
		rows = [frappe._dict(shift_type="Pagi"), frappe._dict(shift_type="Pagi Khusus")]
		with patch("frappe.get_all", return_value=rows), patch("frappe.db.get_value", return_value="Green"):
			options = roster._shift_options("Outlet A")
		self.assertEqual([option["value"] for option in options], ["Pagi", "Pagi Khusus"])


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
