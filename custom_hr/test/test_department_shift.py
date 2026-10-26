"""Department auto shift: settings validation and the IN-time resolver (division OP example)."""

import unittest
from copy import deepcopy
from datetime import date, datetime
from unittest.mock import patch

import frappe

from custom_hr.services import department_shift as svc

MON_THU = {"days": "Senin-Kamis"}
FRI = {"days": "Jumat"}
MONDAY, FRIDAY, SATURDAY = date(2026, 11, 9), date(2026, 11, 13), date(2026, 11, 14)

# name: (start, end, weekday flags)
OP = {
	"Pagi Senin-Kamis": ("06:00:00", "15:00:00", MON_THU),
	"Pagi Jumat": ("06:00:00", "15:30:00", FRI),
	"Siang Senin-Kamis": ("12:00:00", "21:00:00", MON_THU),
	"Siang Jumat": ("11:30:00", "21:00:00", FRI),
}


def shift_type(name, start, end):
	return frappe._dict(
		name=name, modified=datetime(2026, 10, 1), start_time=start, end_time=end,
		determine_check_in_and_check_out="Strictly based on Log Type in Employee Checkin",
		working_hours_calculation_based_on="First Check-in and Last Check-out",
		enable_auto_attendance=1, enable_late_entry_marking=1, late_entry_grace_period=0,
		enable_early_exit_marking=1, early_exit_grace_period=0, working_hours_threshold_for_half_day=0,
		working_hours_threshold_for_absent=0, mark_auto_attendance_on_holidays=0, allow_overtime=0, overtime_type=None,
	)


class DepartmentCase(unittest.TestCase):
	def setUp(self):
		self.table = deepcopy(OP)
		self.employee = frappe._dict(status="Active", department="OP - TEST")
		self.department = frappe._dict(
			enable_auto_shift=1, auto_shift_transition_minutes=30, auto_shift_allow_unscheduled_days=0,
			auto_shift_effective_from="2026-10-01 00:00:00",
		)
		for target, side_effect in (
			("frappe.db.get_value", self.get_value),
			("frappe.get_all", self.get_all),
			(f"{svc.__name__}.get_system_timezone", lambda: "Asia/Jakarta"),
		):
			patcher = patch(target, side_effect=side_effect)
			self.addCleanup(patcher.stop)
			patcher.start()

	def get_value(self, doctype, name, fields=None, **kwargs):
		return deepcopy(self.employee if doctype == "Employee" else self.department)

	def get_all(self, doctype, filters=None, fields=None, **kwargs):
		if doctype == "Outlet Shift":
			return [
				{"shift_type": name, "enabled": 1, "days": "", **days}
				for name, (_start, _end, days) in self.table.items()
			]
		return [shift_type(name, start, end) for name, (start, end, _days) in self.table.items() if name in filters["name"][1]]

	def resolve(self, day, clock, **kwargs):
		return svc.resolve_department_shift("EMP-1", datetime.combine(day, datetime.strptime(clock, "%H:%M:%S").time()), **kwargs)


class TestResolveDepartmentShift(DepartmentCase):
	def test_monday_morning_matches_pagi(self):
		result = self.resolve(MONDAY, "06:05:00")
		self.assertTrue(result["applies"] and result["matched"])
		self.assertEqual(result["checkin_values"]["shift"], "Pagi Senin-Kamis")
		self.assertEqual(result["checkin_values"]["attendance_source"], "Department")

	def test_first_window_opens_at_midnight(self):
		self.assertEqual(self.resolve(MONDAY, "02:00:00")["checkin_values"]["shift"], "Pagi Senin-Kamis")

	def test_siang_takes_over_at_the_transition(self):
		self.assertEqual(self.resolve(MONDAY, "11:29:59")["checkin_values"]["shift"], "Pagi Senin-Kamis")
		self.assertEqual(self.resolve(MONDAY, "11:30:00")["checkin_values"]["shift"], "Siang Senin-Kamis")

	def test_friday_split_is_at_1100(self):
		self.assertEqual(self.resolve(FRIDAY, "10:59:59")["checkin_values"]["shift"], "Pagi Jumat")
		self.assertEqual(self.resolve(FRIDAY, "11:00:00")["checkin_values"]["shift"], "Siang Jumat")

	def test_after_the_last_shift_on_a_shift_day_is_refused(self):
		for allow in (0, 1):
			self.department.auto_shift_allow_unscheduled_days = allow
			result = self.resolve(MONDAY, "22:00:00")
			self.assertFalse(result["matched"])
			self.assertEqual(result["code"], "outside_checkin_window")
			self.assertFalse(result["unscheduled_day"])

	def test_saturday_is_unscheduled_with_the_option_on(self):
		self.department.auto_shift_allow_unscheduled_days = 1
		result = self.resolve(SATURDAY, "09:00:00")
		self.assertFalse(result["matched"])
		self.assertEqual(result["code"], "unscheduled_day")
		self.assertTrue(result["unscheduled_day"])

	def test_saturday_without_the_option_is_refused(self):
		result = self.resolve(SATURDAY, "09:00:00")
		self.assertEqual(result["code"], "outside_checkin_window")
		self.assertFalse(result["unscheduled_day"])

	def test_actual_end_is_the_end_of_the_shift_day(self):
		values = self.resolve(MONDAY, "06:05:00")["checkin_values"]
		self.assertEqual(values["shift_start"], "2026-11-09 06:00:00")
		self.assertEqual(values["shift_end"], "2026-11-09 15:00:00")
		self.assertEqual(values["shift_actual_end"], "2026-11-09 23:59:59")

	def test_before_effective_from_does_not_apply(self):
		self.department.auto_shift_effective_from = "2026-12-01 00:00:00"
		result = self.resolve(MONDAY, "06:05:00")
		self.assertFalse(result["applies"])
		self.assertEqual(result["code"], "not_effective_yet")

	def test_department_off_or_no_department_does_not_apply(self):
		self.department.enable_auto_shift = 0
		self.assertFalse(self.resolve(MONDAY, "06:05:00")["applies"])
		self.department.enable_auto_shift = 1
		self.employee.department = None
		self.assertFalse(self.resolve(MONDAY, "06:05:00")["applies"])
		self.employee.department = "OP - TEST"
		self.employee.status = "Left"
		self.assertFalse(self.resolve(MONDAY, "06:05:00")["applies"])

	def test_same_start_shifts_require_a_choice(self):
		self.table["Pagi Khusus"] = ("06:00:00", "10:00:00", {})
		result = self.resolve(MONDAY, "07:00:00")
		self.assertFalse(result["matched"])
		self.assertEqual(result["code"], "shift_choice_required")
		self.assertEqual(result["choices"], ["Pagi Khusus", "Pagi Senin-Kamis"])

	def test_chosen_shift_is_matched_and_a_foreign_one_is_refused(self):
		self.table["Pagi Khusus"] = ("06:00:00", "10:00:00", {})
		self.assertEqual(self.resolve(MONDAY, "07:00:00", chosen_shift="Pagi Khusus")["checkin_values"]["shift"], "Pagi Khusus")
		result = self.resolve(MONDAY, "07:00:00", chosen_shift="Siang Jumat")
		self.assertEqual(result["code"], "invalid_shift_choice")

	def test_day_has_shift_follows_the_weekday_columns(self):
		rows = [frappe._dict(shift_type="A", enabled=1, **MON_THU), frappe._dict(shift_type="B", enabled=0, days="Sabtu")]
		self.assertTrue(svc.day_has_shift(rows, MONDAY))
		self.assertFalse(svc.day_has_shift(rows, FRIDAY))
		self.assertFalse(svc.day_has_shift(rows, SATURDAY))  # the Saturday row is disabled


class TestDepartmentSettings(unittest.TestCase):
	def department(self, rows=(), **values):
		return frappe._dict({"enable_auto_shift": 1, "auto_shift_transition_minutes": 30, "auto_shifts": list(rows), **values})

	def validate(self, doc):
		with patch(f"{svc.__name__}.validate_shift_rows") as rows:
			svc.validate_department(doc)
		return rows

	def test_enabling_stamps_effective_from_once(self):
		doc = self.department([frappe._dict(shift_type="A", enabled=1)])
		self.validate(doc)
		stamped = doc.auto_shift_effective_from
		self.assertTrue(stamped)
		self.validate(doc)
		self.assertEqual(doc.auto_shift_effective_from, stamped)

	def test_enabling_without_active_shift_rows_is_rejected(self):
		for rows in ([], [frappe._dict(shift_type="A", enabled=0)]):
			with self.subTest(rows=rows), self.assertRaises(frappe.ValidationError):
				self.validate(self.department(rows))

	def test_disabled_department_needs_no_rows_and_is_not_stamped(self):
		doc = self.department(enable_auto_shift=0)
		self.validate(doc)
		self.assertFalse(doc.get("auto_shift_effective_from"))

	def test_rows_are_validated_like_an_outlet_table(self):
		doc = self.department([frappe._dict(shift_type="A", enabled=1)])
		rows = self.validate(doc)
		rows.assert_called_once_with(doc.auto_shifts)

	def test_transition_must_be_below_a_day(self):
		with self.assertRaises(frappe.ValidationError):
			self.validate(self.department([frappe._dict(shift_type="A", enabled=1)], auto_shift_transition_minutes=1440))


class Checkin(frappe._dict):
	"""Stand-in for an Employee Checkin document: item access, update(), is_new()."""

	def is_new(self):
		return self.get("_new", True)


class TestApplyDepartmentShift(unittest.TestCase):
	VALUES = {
		"attendance_source": "Department", "shift": "Pagi Senin-Kamis", "shift_start": "2026-11-09 06:00:00",
		"shift_end": "2026-11-09 15:00:00", "shift_actual_start": "2026-11-09 00:00:00", "shift_actual_end": "2026-11-09 23:59:59",
	}

	def setUp(self):
		self.resolution = {"applies": True, "matched": True, "code": "matched", "message": "ok", "unscheduled_day": False, "checkin_values": dict(self.VALUES)}
		self.resolver = self.patch(f"{svc.__name__}.resolve_department_shift", side_effect=lambda *a, **k: dict(self.resolution))
		self.assignment = self.patch(f"{svc.__name__}.get_employee_shift", return_value={})
		self.open_in = None
		self.later_out = None
		self.patch("frappe.db.get_value", side_effect=lambda *a, **k: self.open_in)
		self.patch("frappe.db.exists", side_effect=lambda *a, **k: self.later_out)

	def patch(self, target, **kwargs):
		patcher = patch(target, **kwargs)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def doc(self, log_type="IN", **values):
		return Checkin(employee="EMP-1", log_type=log_type, time=datetime(2026, 11, 9, 6, 5), shift=None, offshift=1, **values)

	def test_in_sets_the_shift_fields_and_source(self):
		doc = self.doc()
		self.assertTrue(svc.apply_department_shift(doc))
		for field, value in self.VALUES.items():
			self.assertEqual(doc[field], value)
		self.assertEqual(doc.offshift, 0)

	def test_explicit_shift_assignment_wins(self):
		self.assignment.return_value = {"shift_type": "Whatever"}
		doc = self.doc()
		self.assertFalse(svc.apply_department_shift(doc))
		self.resolver.assert_not_called()
		self.assertIsNone(doc.shift)
		self.assignment.assert_called_once_with("EMP-1", doc.time, False)

	def test_in_with_no_matching_shift_is_refused(self):
		self.resolution.update(matched=False, code="outside_checkin_window", message="Tidak ada shift", checkin_values=None)
		with self.assertRaisesRegex(frappe.ValidationError, "Tidak ada shift"):
			svc.apply_department_shift(self.doc())

	def test_choice_required_without_a_choice_is_refused(self):
		self.resolution.update(matched=False, code="shift_choice_required", message="Pilih shift Anda", checkin_values=None)
		with self.assertRaisesRegex(frappe.ValidationError, "Pilih shift Anda"):
			svc.apply_department_shift(self.doc())

	def test_unscheduled_day_falls_back_to_native(self):
		self.resolution.update(matched=False, code="unscheduled_day", unscheduled_day=True, checkin_values=None)
		doc = self.doc()
		self.assertFalse(svc.apply_department_shift(doc))
		self.assertEqual(doc.offshift, 1)

	def test_historical_in_resolves_the_given_time_not_now(self):
		doc = self.doc()
		doc.time = datetime(2026, 11, 2, 7, 0)
		svc.apply_department_shift(doc)
		self.assertEqual(self.resolver.call_args.args[1], datetime(2026, 11, 2, 7, 0))

	def test_chosen_shift_field_is_passed_to_the_resolver(self):
		doc = self.doc()
		doc.shift = "Pagi Khusus"
		svc.apply_department_shift(doc)
		self.assertEqual(self.resolver.call_args.kwargs["chosen_shift"], "Pagi Khusus")

	def test_not_applicable_employee_returns_false(self):
		self.resolution.update(applies=False, matched=False, code="not_applicable", checkin_values=None)
		doc = self.doc()
		self.assertFalse(svc.apply_department_shift(doc))
		self.assertIsNone(doc.shift)

	def test_out_copies_the_shift_from_the_open_in(self):
		self.open_in = frappe._dict({**self.VALUES, "name": "IN-1", "time": datetime(2026, 11, 9, 6, 5)})
		doc = self.doc("OUT")
		doc.time = datetime(2026, 11, 9, 15, 5)
		self.assertTrue(svc.apply_department_shift(doc))
		self.assertEqual(doc.shift, "Pagi Senin-Kamis")
		self.assertEqual(doc.attendance_source, "Department")
		self.assertEqual(doc.shift_actual_end, "2026-11-09 23:59:59")
		self.resolver.assert_not_called()

	def test_out_without_a_department_in_falls_back_to_native(self):
		doc = self.doc("OUT")
		self.assertFalse(svc.apply_department_shift(doc))
		self.open_in = frappe._dict({**self.VALUES, "attendance_source": "Outlet", "name": "IN-1", "time": datetime(2026, 11, 9, 6, 5)})
		self.assertFalse(svc.apply_department_shift(doc))

	def test_out_of_a_closed_session_falls_back_to_native(self):
		self.open_in = frappe._dict({**self.VALUES, "name": "IN-1", "time": datetime(2026, 11, 9, 6, 5)})
		self.later_out = "OUT-0"
		self.assertFalse(svc.apply_department_shift(self.doc("OUT")))

	def test_a_saved_checkin_is_left_alone(self):
		saved = self.doc(_new=False, attendance_source="Department")
		self.assertTrue(svc.apply_department_shift(saved))
		self.resolver.assert_not_called()
		self.assertFalse(svc.apply_department_shift(self.doc(_new=False)))


class TestMissingCheckoutIsPresent(unittest.TestCase):
	"""A Department IN with no OUT: nothing before its deadline, Present with the shift's hours after it."""

	SHIFT_START, SHIFT_END = datetime(2026, 11, 9, 6, 0), datetime(2026, 11, 9, 15, 0)
	DEADLINE = datetime(2026, 11, 9, 23, 59, 59)

	def setUp(self):
		from custom_hr.overrides.shift_type import CustomShiftType

		self.shift = frappe.new_doc("Shift Type")
		self.assertIsInstance(self.shift, CustomShiftType)
		self.shift.update({
			"determine_check_in_and_check_out": "Strictly based on Log Type in Employee Checkin",
			"working_hours_calculation_based_on": "First Check-in and Last Check-out",
			"enable_late_entry_marking": 1, "late_entry_grace_period": 10, "enable_early_exit_marking": 1, "early_exit_grace_period": 0,
		})

	def log(self, log_type, hour, minute=0, department=True, employee="EMP-1", name=None):
		return frappe._dict(
			name=name or f"{employee}-{log_type}", employee=employee, log_type=log_type,
			time=datetime(2026, 11, 9, hour, minute), shift_start=self.SHIFT_START, shift_end=self.SHIFT_END,
			shift_actual_end=self.DEADLINE, department_mode=department,
		)

	def attendance(self, logs, absent=4, half=2):
		return self.shift.get_attendance(logs, absent, half)

	def test_lone_in_after_the_deadline_is_present_with_standard_hours(self):
		status, hours, late, early, in_time, out_time = self.attendance([self.log("IN", 6, 5)])
		self.assertEqual((status, hours, late, early), ("Present", 9.0, False, False))
		self.assertEqual(in_time, datetime(2026, 11, 9, 6, 5))
		self.assertIsNone(out_time)

	def test_late_entry_is_marked_by_the_grace_period(self):
		self.assertTrue(self.attendance([self.log("IN", 6, 20)])[2])
		self.assertFalse(self.attendance([self.log("IN", 6, 10)])[2])

	def test_group_with_an_out_follows_native(self):
		status, hours, _late, early, _in, out_time = self.attendance([self.log("IN", 6), self.log("OUT", 14, name="OUT-1")])
		self.assertEqual((status, hours, early, out_time), ("Present", 8.0, True, datetime(2026, 11, 9, 14)))

	def test_native_lone_in_is_untouched(self):
		status, hours, *_rest = self.attendance([self.log("IN", 6, 5, department=False)])
		self.assertEqual((status, hours), ("Absent", 0))

	def filtered(self, logs, now, departments=("EMP-1-IN", "EMP-2-IN")):
		with patch("custom_hr.overrides.shift_type.now_datetime", return_value=now), patch.object(type(self.shift), "_department_names", return_value=set(departments)):
			return [row["name"] for row in self.shift._without_open_department_sessions(logs)]

	def test_lone_in_before_the_deadline_creates_no_attendance(self):
		logs = [self.log("IN", 6, 5), self.log("IN", 7, employee="EMP-2")]
		self.assertEqual(self.filtered(logs, datetime(2026, 11, 9, 20, 0)), [])
		self.assertEqual(self.filtered(logs, datetime(2026, 11, 10, 0, 1)), ["EMP-1-IN", "EMP-2-IN"])

	def test_complete_pairs_and_other_sources_are_never_held_back(self):
		pair = [self.log("IN", 6), self.log("OUT", 14, name="OUT-1")]
		native = [self.log("IN", 7, employee="EMP-3", department=False)]
		self.assertEqual(self.filtered(pair + native, datetime(2026, 11, 9, 10, 0), departments=("EMP-1-IN", "OUT-1")), ["EMP-1-IN", "OUT-1", "EMP-3-IN"])
