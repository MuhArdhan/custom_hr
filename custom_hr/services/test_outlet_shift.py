# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""T04 tests: schedule calculation and mocked reads, never writes or activation."""

import json
import unittest
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

import frappe

from custom_hr.services.outlet_shift import (
	ShiftConfigurationError,
	build_shift_windows,
	get_employee_attendance_mode,
	resolve_outlet_shift,
)

MODULE = "custom_hr.services.outlet_shift"
DAY = date(2026, 10, 15)
FIRST = "Shift 1 05.00 - 13.00"
LAST = "Shift 2 10.00 - 18.00"


def make_shift(name=FIRST, start="05:00:00", end="13:00:00", **overrides):
	return frappe._dict(
		{
			"name": name,
			"modified": datetime(2026, 10, 15, 8),
			"start_time": start,
			"end_time": end,
			"determine_check_in_and_check_out": "Strictly based on Log Type in Employee Checkin",
			"working_hours_calculation_based_on": "First Check-in and Last Check-out",
			"enable_auto_attendance": 0,
			"enable_late_entry_marking": 1,
			"late_entry_grace_period": 5,
			"enable_early_exit_marking": 1,
			"early_exit_grace_period": 0,
			"working_hours_threshold_for_half_day": 0,
			"working_hours_threshold_for_absent": 0,
			"mark_auto_attendance_on_holidays": 0,
			"allow_overtime": 0,
			"overtime_type": None,
			**overrides,
		}
	)


class TestShiftWindows(unittest.TestCase):
	def setUp(self):
		self.shifts = [make_shift(), make_shift(LAST, "10:00:00", "18:00:00")]

	def test_first_window_opens_at_midnight(self):
		first, _last = build_shift_windows(self.shifts, DAY, 30)
		self.assertEqual(first.checkin_start, datetime(2026, 10, 15))
		self.assertEqual(first.shift_start, datetime(2026, 10, 15, 5))
		self.assertEqual(first.shift_end, datetime(2026, 10, 15, 13))

	def test_transition_is_exclusive_for_first_inclusive_for_next(self):
		first, last = build_shift_windows(self.shifts, DAY, 30)
		before, boundary = datetime(2026, 10, 15, 9, 29, 59), datetime(2026, 10, 15, 9, 30)
		self.assertTrue(first.contains(before))
		self.assertFalse(last.contains(before))
		self.assertFalse(first.contains(boundary))
		self.assertTrue(last.contains(boundary))

	def test_last_window_ends_at_scheduled_end_inclusively(self):
		_last = build_shift_windows(self.shifts, DAY, 30)[1]
		self.assertTrue(_last.contains(datetime(2026, 10, 15, 18)))
		self.assertFalse(_last.contains(datetime(2026, 10, 15, 18, 0, 1)))

	def test_row_order_does_not_change_selection(self):
		self.assertEqual(
			[window.as_dict() for window in build_shift_windows(self.shifts, DAY, 30)],
			[window.as_dict() for window in build_shift_windows(list(reversed(self.shifts)), DAY, 30)],
		)

	def test_three_shifts_have_nonoverlapping_checkin_windows(self):
		self.shifts.append(make_shift("Middle", "08:00:00", "16:00:00"))
		windows = build_shift_windows(self.shifts, DAY, 30)
		self.assertEqual([w.shift for w in windows], [FIRST, "Middle", LAST])
		for timestamp, expected in [(datetime(2026, 10, 15, 7, 29, 59), FIRST), (datetime(2026, 10, 15, 7, 30), "Middle"), (datetime(2026, 10, 15, 9, 30), LAST)]:
			with self.subTest(timestamp=timestamp):
				self.assertEqual([w.shift for w in windows if w.contains(timestamp)], [expected])

	def test_zero_transition_switches_at_next_start(self):
		first, last = build_shift_windows(self.shifts, DAY, 0)
		self.assertEqual(first.checkin_end, datetime(2026, 10, 15, 10))
		self.assertEqual(last.checkin_start, first.checkin_end)
		self.assertFalse(first.end_inclusive)

	def test_native_buffers_do_not_expand_custom_windows(self):
		for shift in self.shifts:
			shift.begin_check_in_before_shift_start_time = 120
			shift.allow_check_out_after_shift_end_time = 360
		first, last = build_shift_windows(self.shifts, DAY, 30)
		self.assertEqual(first.checkin_start.time(), time.min)
		self.assertEqual(last.checkin_end.time(), time(18))

	def test_completed_shift_is_not_reopened_in_a_schedule_gap(self):
		self.shifts[0].end_time = "08:00:00"
		first, last = build_shift_windows(self.shifts, DAY, 30)
		self.assertEqual(first.checkin_end.time(), time(8))
		self.assertTrue(first.end_inclusive)
		self.assertFalse(any(w.contains(datetime(2026, 10, 15, 8, 30)) for w in (first, last)))

	def test_next_shift_wins_when_transition_equals_previous_end(self):
		self.shifts[0].end_time = "09:30:00"
		first, last = build_shift_windows(self.shifts, DAY, 30)
		self.assertFalse(first.contains(datetime(2026, 10, 15, 9, 30)))
		self.assertTrue(last.contains(datetime(2026, 10, 15, 9, 30)))

	def test_overnight_shift_has_correct_end_date(self):
		window = build_shift_windows([make_shift("Night", "22:00:00", "06:00:00")], DAY, 30)[0]
		self.assertEqual(window.work_date, DAY)
		self.assertEqual(window.shift_end, datetime(2026, 10, 16, 6))
		self.assertTrue(window.contains(datetime(2026, 10, 16, 6)))
		self.assertFalse(window.contains(datetime(2026, 10, 16, 6, 0, 1)))

	def test_sql_timedelta_clocks_are_supported(self):
		self.shifts[0].start_time = timedelta(hours=5)
		self.shifts[0].end_time = timedelta(hours=13)
		self.assertEqual(build_shift_windows(self.shifts, DAY, 30)[0].shift_start.hour, 5)

	def test_empty_shift_list_is_rejected(self):
		with self.assertRaisesRegex(ShiftConfigurationError, "belum memiliki shift aktif"):
			build_shift_windows([], DAY, 30)

	def test_duplicate_shift_names_are_rejected(self):
		with self.assertRaisesRegex(ShiftConfigurationError, "duplikat"):
			build_shift_windows([self.shifts[0], self.shifts[0]], DAY, 30)

	def test_duplicate_start_times_are_rejected(self):
		self.shifts[1].start_time = "05:00:00"
		with self.assertRaisesRegex(ShiftConfigurationError, "bertabrakan"):
			build_shift_windows(self.shifts, DAY, 30)

	def test_same_start_and_end_is_rejected(self):
		self.shifts[0].end_time = "05:00:00"
		with self.assertRaisesRegex(ShiftConfigurationError, "sama dengan jam selesai"):
			build_shift_windows(self.shifts, DAY, 30)

	def test_invalid_transition_is_rejected(self):
		for value in (-1, 1440, "NaN", "Infinity", "0.5", None):
			with self.subTest(value=value), self.assertRaises(ShiftConfigurationError):
				build_shift_windows(self.shifts, DAY, value)

	def test_transition_cannot_move_a_window_to_previous_work_date(self):
		shifts = [make_shift("A", "00:05:00", "08:00:00"), make_shift("B", "00:15:00", "09:00:00")]
		with self.assertRaisesRegex(ShiftConfigurationError, "jendela IN tidak valid"):
			build_shift_windows(shifts, DAY, 30)

	def test_invalid_clocks_are_rejected(self):
		for value in (None, "", "25:00:00", "23:60:00", "23:59:60", timedelta(hours=-1), timedelta(days=1), time(5, microsecond=1)):
			with self.subTest(value=value), self.assertRaises(ShiftConfigurationError):
				shift = make_shift(start=value)
				build_shift_windows([shift], DAY, 30)

	def test_invalid_policy_numbers_are_rejected(self):
		for field, value in [("late_entry_grace_period", -1), ("early_exit_grace_period", "0.5"), ("working_hours_threshold_for_absent", "NaN"), ("working_hours_threshold_for_half_day", -1), ("allow_overtime", 2)]:
			with self.subTest(field=field), self.assertRaises(ShiftConfigurationError):
				build_shift_windows([make_shift(**{field: value})], DAY, 30)

	def test_invalid_calculation_methods_are_rejected(self):
		for field in ("determine_check_in_and_check_out", "working_hours_calculation_based_on"):
			with self.subTest(field=field), self.assertRaises(ShiftConfigurationError):
				build_shift_windows([make_shift(**{field: "unknown"})], DAY, 30)

	def test_threshold_cannot_overflow_json_numbers(self):
		with self.assertRaisesRegex(ShiftConfigurationError, "rentang angka"):
			build_shift_windows([make_shift(working_hours_threshold_for_absent="1e10000")], DAY, 30)

	def test_enabled_overtime_requires_a_type(self):
		with self.assertRaisesRegex(ShiftConfigurationError, "Jenis lembur"):
			build_shift_windows([make_shift(allow_overtime=1)], DAY, 30)

	def test_window_export_is_json_ready(self):
		json.dumps([w.as_dict() for w in build_shift_windows(self.shifts, DAY, 30)], allow_nan=False)


class TestOutletShiftResolver(unittest.TestCase):
	def setUp(self):
		self.employee = frappe._dict(name="EMP-TEST", status="Active", outlet="Outlet Test", company="Company Test")
		self.outlet = frappe._dict(
			name="Outlet Test", company="Company Test", is_active=1, holiday_list="Outlet Holidays",
			modified=datetime(2026, 10, 15, 8), enable_outlet_auto_shift=1,
			outlet_auto_shift_effective_from="2026-10-15 00:00:00", shift_transition_minutes=30,
			shifts=[frappe._dict(shift_type=FIRST, enabled=1), frappe._dict(shift_type=LAST, enabled=1)],
		)
		self.shifts = [make_shift(), make_shift(LAST, "10:00:00", "18:00:00")]
		self.mock_timezone = self.mock("get_system_timezone", return_value="Asia/Jakarta")
		self.employee_query = self.mock("frappe.db.get_value", side_effect=self.read_employee)
		self.outlet_query = self.mock("frappe.get_doc", side_effect=self.read_outlet)
		self.shift_query = self.mock("frappe.get_all", side_effect=self.read_shifts)

	def mock(self, name, **kwargs):
		patcher = patch(f"{MODULE}.{name}", **kwargs)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def read_employee(self, doctype, name, fields, **kwargs):
		self.assertEqual(doctype, "Employee")
		return deepcopy(self.employee)

	def read_outlet(self, doctype, name):
		self.assertEqual(doctype, "Outlet")
		return deepcopy(self.outlet)

	def read_shifts(self, doctype, filters, fields):
		self.assertEqual(doctype, "Shift Type")
		return [deepcopy(shift) for shift in self.shifts if shift.name in filters["name"][1]]

	def resolve(self, stamp="2026-10-15 10:00:00", **kwargs):
		return resolve_outlet_shift("EMP-TEST", stamp, **kwargs)

	def test_delanggu_boundaries(self):
		for clock, expected in [("00:00:00", FIRST), ("02:00:00", FIRST), ("05:05:00", FIRST), ("09:29:59", FIRST), ("09:30:00", LAST), ("10:00:00", LAST), ("18:00:00", LAST)]:
			with self.subTest(clock=clock):
				result = self.resolve("2026-10-15 " + clock)
				self.assertTrue(result["matched"])
				self.assertEqual(result["selection"]["shift"], expected)
				self.assertEqual(len(result["candidates"]), 1)

	def test_after_last_shift_has_reason_not_native_fallback(self):
		result = self.resolve("2026-10-15 18:00:01")
		self.assertFalse(result["matched"])
		self.assertEqual(result["code"], "outside_checkin_window")
		self.assertEqual(result["mode"], "Outlet")
		self.assertIsNone(result["checkin_values"])
		self.assertTrue(result["message"])

	def test_new_date_does_not_reopen_yesterdays_last_shift(self):
		result = self.resolve("2026-10-16 00:00:00")
		self.assertEqual(result["selection"]["shift"], FIRST)
		self.assertEqual(result["selection"]["shift_work_date"], "2026-10-16")

	def test_context_lookup_does_not_read_shift_types(self):
		context = get_employee_attendance_mode("EMP-TEST", "2026-10-15 10:00:00")
		self.assertEqual(context["mode"], "Outlet")
		self.assertTrue(context["mode_applies"])
		self.shift_query.assert_not_called()

	def test_disabled_mode_returns_native_without_selecting(self):
		self.outlet.enable_outlet_auto_shift = 0
		result = self.resolve()
		self.assertEqual(result["mode"], "Native")
		self.assertEqual(result["code"], "mode_disabled")
		self.assertFalse(result["matched"])
		self.shift_query.assert_not_called()

	def test_preview_reads_disabled_mode_without_activating_it(self):
		self.outlet.enable_outlet_auto_shift = 0
		self.outlet.outlet_auto_shift_effective_from = None
		before = deepcopy(self.outlet)
		result = self.resolve(preview=True)
		self.assertTrue(result["matched"])
		self.assertTrue(result["preview"])
		self.assertFalse(result["mode_applies"])
		self.assertEqual(result["mode"], "Native")
		self.assertEqual(self.outlet, before)

	def test_activation_time_is_inclusive_and_compared_in_site_timezone(self):
		self.outlet.outlet_auto_shift_effective_from = "2026-10-15T02:30:00Z"
		self.assertEqual(self.resolve("2026-10-15 09:29:59")["code"], "not_effective_yet")
		self.assertTrue(self.resolve("2026-10-15 09:30:00")["mode_applies"])

	def test_preview_can_inspect_a_future_activation(self):
		self.outlet.outlet_auto_shift_effective_from = "2026-11-01 00:00:00"
		result = self.resolve(preview=True)
		self.assertTrue(result["matched"])
		self.assertFalse(result["mode_applies"])

	def test_enabled_mode_without_activation_time_is_invalid_even_in_preview(self):
		self.outlet.outlet_auto_shift_effective_from = None
		self.assertEqual(self.resolve(preview=True)["code"], "invalid_configuration")
		self.shift_query.assert_not_called()

	def test_invalid_activation_time_is_reported(self):
		self.outlet.outlet_auto_shift_effective_from = "not a time"
		self.assertEqual(self.resolve()["code"], "invalid_configuration")

	def test_employee_without_outlet_uses_native_even_in_preview(self):
		self.employee.outlet = None
		result = self.resolve(preview=True)
		self.assertEqual(result["code"], "no_outlet")
		self.assertEqual(result["mode"], "Native")
		self.assertFalse(result["matched"])
		self.outlet_query.assert_not_called()

	def test_missing_employee_is_reported(self):
		self.employee = None
		self.assertEqual(self.resolve()["code"], "employee_not_found")
		self.outlet_query.assert_not_called()

	def test_inactive_employee_is_not_selected(self):
		self.employee.status = "Inactive"
		self.assertEqual(self.resolve(preview=True)["code"], "employee_inactive")
		self.outlet_query.assert_not_called()

	def test_missing_outlet_is_reported(self):
		self.outlet_query.side_effect = frappe.DoesNotExistError
		self.assertEqual(self.resolve()["code"], "outlet_not_found")

	def test_inactive_outlet_cannot_be_previewed(self):
		self.outlet.is_active = 0
		self.assertEqual(self.resolve(preview=True)["code"], "outlet_inactive")

	def test_employee_outlet_company_mismatch_uses_employee_company(self):
		self.outlet.company = "Other Company"
		result = self.resolve()
		self.assertTrue(result["matched"])
		policy = result["checkin_values"]["shift_policy_snapshot"]
		self.assertEqual(policy["company"], self.employee.company)
		self.assertEqual(policy["company_source"], "Employee")
		self.assertEqual(policy["outlet"], self.outlet.name)
		self.assertEqual(policy["holiday_list"], self.outlet.holiday_list)

	def test_missing_employee_company_is_rejected_without_outlet_fallback(self):
		self.employee.company = None
		self.assertEqual(self.resolve()["code"], "invalid_configuration")

	def test_preview_with_different_company_preserves_employee_company_source(self):
		self.outlet.company = "Other Company"
		self.outlet.enable_outlet_auto_shift = 0
		result = self.resolve(preview=True)
		self.assertTrue(result["matched"])
		self.assertFalse(result["mode_applies"])
		self.assertEqual(result["checkin_values"]["shift_policy_snapshot"]["company"], self.employee.company)

	def test_empty_employee_identifier_does_not_query_db(self):
		result = resolve_outlet_shift("", "2026-10-15 10:00:00")
		self.assertEqual(result["code"], "employee_not_found")
		self.employee_query.assert_not_called()

	def test_invalid_timestamp_does_not_query_db(self):
		for stamp in ("", "not a date", date(2026, 10, 15), timedelta(hours=1)):
			with self.subTest(stamp=stamp):
				self.assertEqual(self.resolve(stamp)["code"], "invalid_timestamp")
		self.employee_query.assert_not_called()

	def test_invalid_timezone_is_reported(self):
		self.mock_timezone.return_value = "Invalid/Timezone"
		self.assertEqual(self.resolve()["code"], "invalid_timestamp")
		self.employee_query.assert_not_called()

	def test_omitted_timestamp_uses_server_now(self):
		self.mock("now_datetime", return_value=datetime(2026, 10, 15, 9, 30))
		self.assertEqual(self.resolve(None)["selection"]["shift"], LAST)

	def test_offset_timestamp_is_converted_before_selection(self):
		result = self.resolve("2026-10-15T02:30:00+00:00")
		self.assertEqual(result["evaluated_at"], "2026-10-15 09:30:00")
		self.assertEqual(result["selection"]["shift"], LAST)

	def test_timezone_conversion_can_change_work_date(self):
		result = self.resolve("2026-10-14T18:00:00Z")
		self.assertEqual(result["selection"]["shift_work_date"], "2026-10-15")
		self.assertEqual(result["selection"]["shift"], FIRST)

	def test_timestamp_has_same_second_precision_as_employee_checkin(self):
		result = self.resolve("2026-10-15 09:29:59.999999")
		self.assertEqual(result["evaluated_at"], "2026-10-15 09:29:59")
		self.assertEqual(result["selection"]["shift"], FIRST)

	def test_only_enabled_outlet_shifts_are_loaded_in_one_query(self):
		self.outlet.shifts[1].enabled = 0
		result = self.resolve()
		self.assertEqual(result["selection"]["shift"], FIRST)
		self.shift_query.assert_called_once()
		self.assertEqual(self.shift_query.call_args.kwargs["filters"], {"name": ["in", [FIRST]]})

	def test_all_shifts_disabled_is_invalid(self):
		for row in self.outlet.shifts:
			row.enabled = 0
		self.assertEqual(self.resolve()["code"], "invalid_configuration")

	def test_duplicate_active_rows_is_invalid(self):
		self.outlet.shifts.append(deepcopy(self.outlet.shifts[0]))
		self.assertEqual(self.resolve()["code"], "invalid_configuration")

	def test_missing_linked_shift_is_invalid_not_native_fallback(self):
		self.shifts.pop()
		result = self.resolve()
		self.assertEqual(result["code"], "invalid_configuration")
		self.assertEqual(result["mode"], "Outlet")
		self.assertFalse(result["matched"])

	def test_missing_holiday_list_still_resolves_outlet_shift(self):
		self.outlet.holiday_list = None
		result = self.resolve()
		self.assertTrue(result["matched"])
		self.assertEqual(result["mode"], "Outlet")

	def test_bad_configuration_returns_a_reason_instead_of_throwing(self):
		self.shifts[0].late_entry_grace_period = -1
		result = self.resolve()
		self.assertFalse(result["matched"])
		self.assertEqual(result["code"], "invalid_configuration")
		self.assertTrue(result["message"])

	def test_integral_transition_string_is_normalized_in_snapshot(self):
		self.outlet.shift_transition_minutes = "30.0"
		result = self.resolve()
		self.assertTrue(result["matched"])
		self.assertEqual(result["checkin_values"]["shift_policy_snapshot"]["shift_transition_minutes"], 30)

	def test_snapshot_contains_locked_schedule_and_calculation_policy(self):
		result = self.resolve("2026-10-15 10:09:00")
		values = result["checkin_values"]
		self.assertEqual(values["attendance_source"], "Outlet")
		self.assertEqual(values["shift"], LAST)
		self.assertEqual(values["shift_start"], "2026-10-15 10:00:00")
		self.assertEqual(values["shift_end"], "2026-10-15 18:00:00")
		self.assertEqual(values["shift_actual_start"], "2026-10-15 09:30:00")
		self.assertEqual(values["shift_actual_end"], "2026-10-15 23:59:59")
		snapshot = values["shift_policy_snapshot"]
		self.assertEqual(snapshot["version"], 1)
		self.assertEqual(snapshot["late_entry_grace_period"], 5)
		self.assertEqual(snapshot["early_exit_grace_period"], 0)
		self.assertEqual(snapshot["standard_working_hours"], 8)
		self.assertEqual(snapshot["holiday_list"], "Outlet Holidays")
		self.assertEqual(snapshot["timezone"], "Asia/Jakarta")
		self.assertEqual(snapshot["checkout_deadline"], "2026-10-15 23:59:59")
		self.assertEqual(snapshot["daily_session_limit"], 1)
		self.assertEqual(snapshot["missing_checkout_hours_source"], "Locked Shift Allocation")
		self.assertNotIn("out_time", values)
		self.assertNotIn("time", values)
		json.dumps(result, allow_nan=False)

	def test_snapshot_does_not_change_when_master_changes(self):
		result = self.resolve()
		old_snapshot = deepcopy(result["checkin_values"]["shift_policy_snapshot"])
		self.shifts[1].late_entry_grace_period = 10
		self.shifts[1].end_time = "19:00:00"
		self.outlet.holiday_list = "New Holidays"
		self.assertEqual(result["checkin_values"]["shift_policy_snapshot"], old_snapshot)
		new_snapshot = self.resolve()["checkin_values"]["shift_policy_snapshot"]
		self.assertEqual(new_snapshot["late_entry_grace_period"], 10)
		self.assertEqual(new_snapshot["standard_working_hours"], 9)

	def test_returned_snapshot_mutation_does_not_leak_to_other_calls(self):
		result = self.resolve()
		result["checkin_values"]["shift_policy_snapshot"]["late_entry_grace_period"] = 999
		self.assertEqual(self.resolve()["checkin_values"]["shift_policy_snapshot"]["late_entry_grace_period"], 5)

	def night_schedule(self):
		self.shifts[1] = make_shift("Night", "22:00:00", "06:00:00")
		self.outlet.shifts[1].shift_type = "Night"

	def test_overnight_snapshot_uses_next_day_end_and_checkout_deadline(self):
		self.night_schedule()
		values = self.resolve("2026-10-15 22:09:00")["checkin_values"]
		self.assertEqual(values["shift"], "Night")
		self.assertEqual(values["shift_work_date"], "2026-10-15")
		self.assertEqual(values["shift_end"], "2026-10-16 06:00:00")
		self.assertEqual(values["checkout_deadline"], "2026-10-16 23:59:59")
		self.assertEqual(values["shift_policy_snapshot"]["standard_working_hours"], 8)

	def test_previous_overnight_and_todays_early_window_are_not_guessed(self):
		self.night_schedule()
		result = self.resolve("2026-10-16 02:00:00")
		self.assertEqual(result["code"], "ambiguous_candidate")
		self.assertEqual(len(result["candidates"]), 2)
		self.assertFalse(result["matched"])
		self.assertIsNone(result["checkin_values"])

	def test_previous_overnight_stops_being_candidate_after_its_end(self):
		self.night_schedule()
		result = self.resolve("2026-10-16 06:00:01")
		self.assertEqual(result["code"], "matched")
		self.assertEqual(result["selection"]["shift"], FIRST)
		self.assertEqual(result["selection"]["shift_work_date"], "2026-10-16")

	def test_datetime_range_overflow_returns_a_reason(self):
		self.night_schedule()
		self.assertEqual(self.resolve("9999-12-31 22:00:00")["code"], "invalid_configuration")

	def test_schedule_gap_returns_no_candidate(self):
		self.shifts[0].end_time = "08:00:00"
		self.assertEqual(self.resolve("2026-10-15 08:30:00")["code"], "outside_checkin_window")

	def test_same_input_is_deterministic_and_does_not_mutate_configuration(self):
		before = deepcopy((self.employee, self.outlet, self.shifts))
		self.assertEqual(self.resolve(), self.resolve())
		self.assertEqual((self.employee, self.outlet, self.shifts), before)
