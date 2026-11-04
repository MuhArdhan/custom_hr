"""Outlet "Shift Manual": the employee picks any shift already open and not yet over."""

import json
import unittest
from datetime import datetime

import frappe

from custom_hr.services.outlet_shift import build_shift_windows, pick_window, row_transitions, shift_mode_on
from custom_hr.services.test_outlet_shift import DAY, make_shift

FIVE, SEVEN = "Shift 05.00 - 13.00", "Shift 07.00 - 15.00"


def at(hour, minute=0):
	return datetime(DAY.year, DAY.month, DAY.day, hour, minute)


class TestManualShiftChoice(unittest.TestCase):
	def setUp(self):
		# Jeda Peralihan 30: in automatic mode the 05:00 shift stops taking INs at 06:30
		self.windows = build_shift_windows([make_shift(FIVE, "05:00:00", "13:00:00"), make_shift(SEVEN, "07:00:00", "15:00:00")], DAY, 30)

	def pick(self, when, chosen=None, manual=True):
		return pick_window(self.windows, when, chosen, no_match_message="none", manual=manual)

	def test_a_late_five_oclock_employee_can_still_pick_the_five_oclock_shift(self):
		window, _ = self.pick(at(6, 55), FIVE)
		self.assertEqual(window.shift, FIVE)
		automatic, _ = self.pick(at(6, 55), manual=False)
		self.assertEqual(automatic.shift, SEVEN)  # what the automatic mode would have recorded

	def test_both_open_shifts_are_offered_in_start_order(self):
		window, outcome = self.pick(at(6, 55))
		self.assertIsNone(window)
		self.assertEqual((outcome["code"], outcome["choices"]), ("shift_choice_required", [FIVE, SEVEN]))

	def test_a_single_open_shift_is_still_chosen_by_the_employee(self):
		window, outcome = self.pick(at(4, 30))  # only the 05:00 shift is open (from midnight); 07:00 opens at 06:30
		self.assertIsNone(window)
		self.assertEqual((outcome["code"], outcome["choices"]), ("shift_choice_required", [FIVE]))
		window, _ = self.pick(at(4, 30), FIVE)
		self.assertEqual(window.shift, FIVE)
		_, outcome = self.pick(at(13, 30))  # the 05:00 shift is over
		self.assertEqual(outcome["choices"], [SEVEN])

	def test_a_shift_not_open_at_that_time_is_refused(self):
		window, outcome = self.pick(at(6, 55), "Shift Lain")
		self.assertIsNone(window)
		self.assertEqual(outcome["code"], "invalid_shift_choice")

	def test_after_every_shift_ended_nothing_is_open(self):
		window, outcome = self.pick(at(15, 30))
		self.assertIsNone(window)
		self.assertEqual(outcome["code"], "outside_checkin_window")

	def test_manual_alone_turns_the_outlet_shift_mode_on(self):
		self.assertTrue(shift_mode_on({"enable_outlet_auto_shift": 0, "manual_shift_choice": 1}))
		self.assertTrue(shift_mode_on({"enable_outlet_auto_shift": 1, "manual_shift_choice": 0}))
		self.assertFalse(shift_mode_on({"enable_outlet_auto_shift": 0, "manual_shift_choice": 0}))

	def test_an_outlet_cannot_be_both_automatic_and_manual(self):
		outlet = frappe.new_doc("Outlet")
		outlet.update({"enable_outlet_auto_shift": 1, "manual_shift_choice": 1, "is_active": 1})
		with self.assertRaisesRegex(frappe.ValidationError, "Pilih salah satu"):
			outlet.validate_auto_shift_activation()

	def test_the_outlet_has_the_manual_checkbox_next_to_the_automatic_one(self):
		order = json.load(open(frappe.get_app_path("custom_hr", "hrm", "doctype", "outlet", "outlet.json")))["field_order"]
		start = order.index("enable_outlet_auto_shift")
		self.assertEqual(order[start : start + 3], ["enable_outlet_auto_shift", "column_break_shift_mode", "manual_shift_choice"])


class TestRowTransition(unittest.TestCase):
	"""Jeda IN on a shift row overrides the outlet default for that shift only."""

	def windows(self, own=None, default=30):
		shifts = [make_shift(FIVE, "05:00:00", "13:00:00"), make_shift(SEVEN, "07:00:00", "15:00:00"), make_shift("Shift 10.00", "10:00:00", "18:00:00")]
		return {w.shift: w for w in build_shift_windows(shifts, DAY, default, own)}

	def test_without_row_values_every_shift_uses_the_default(self):
		windows = self.windows()
		self.assertEqual((windows[SEVEN].checkin_start, windows[FIVE].checkin_end), (at(6, 30), at(6, 30)))
		self.assertEqual(windows["Shift 10.00"].checkin_start, at(9, 30))

	def test_a_row_value_moves_only_that_shift_opening_and_the_cut_of_the_one_before(self):
		windows = self.windows({SEVEN: 5})
		self.assertEqual(windows[SEVEN].checkin_start, at(6, 55))
		self.assertEqual(windows[FIVE].checkin_end, at(6, 55))  # the 05:00 shift keeps taking INs until 06:55
		self.assertEqual(windows["Shift 10.00"].checkin_start, at(9, 30))  # still the default
		self.assertEqual(windows[SEVEN].checkin_end, at(9, 30))

	def test_empty_or_zero_cells_and_disabled_rows_fall_back_to_the_default(self):
		rows = [
			frappe._dict(shift_type=FIVE, enabled=1, transition_minutes=0),
			frappe._dict(shift_type=SEVEN, enabled=1, transition_minutes=5),
			frappe._dict(shift_type="Shift 10.00", enabled=0, transition_minutes=90),
			frappe._dict(shift_type="Shift Kosong", enabled=1, transition_minutes=None),
		]
		self.assertEqual(row_transitions(rows), {SEVEN: 5})
