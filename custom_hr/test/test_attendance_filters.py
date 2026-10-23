"""Gallery / summary / daily-card filters on the attendance of the day (late, early, status, no OUT)."""

import unittest
from unittest.mock import patch

import frappe

from custom_hr import api

DATE = "2026-10-23"


def log(name, employee, log_type, hour):
	return frappe._dict(
		name=name, employee=employee, employee_name=employee, log_type=log_type, time=f"{DATE} {hour}:00:00"
	)


def attendance(employee, **changes):
	row = dict(employee=employee, attendance_date=DATE, status="Present", late_entry=0, early_exit=0, missing_checkout=0)
	return frappe._dict({**row, **changes})


CHECKINS = [
	log("C1", "E1", "IN", "08"), log("C2", "E1", "OUT", "17"),
	log("C3", "E2", "IN", "08"), log("C4", "E3", "IN", "08"), log("C5", "E4", "IN", "08"),
]
ATTENDANCE = [
	attendance("E1", late_entry=1),
	attendance("E2", early_exit=1),
	attendance("E3", late_entry=1, early_exit=1),
	attendance("E4", status="Half Day", missing_checkout=1),
]


class FakeDB:
	"""Just enough of get_all to honour the equality filters these APIs send."""

	def __init__(self):
		self.calls = []

	def get_all(self, doctype, filters=None, fields=None, **kwargs):
		self.calls.append((doctype, dict(filters or {}), kwargs))
		filters = filters or {}
		if doctype == "Attendance":
			rows = [frappe._dict(row) for row in ATTENDANCE]
			for key, value in filters.items():
				if key == "employee":
					rows = [r for r in rows if (r.employee in value[1] if isinstance(value, list) else r.employee == value)]
					continue
				if key in ("attendance_date", "docstatus"):
					continue
				rows = [r for r in rows if r.get(key) == value]
			if kwargs.get("pluck"):
				return list(dict.fromkeys(row[kwargs["pluck"]] for row in rows))
			return rows
		if doctype == "Employee Checkin":
			rows = list(CHECKINS)
			employee = filters.get("employee")
			if isinstance(employee, list):
				rows = [r for r in rows if r.employee in employee[1]]
			elif employee:
				rows = [r for r in rows if r.employee == employee]
			start, length = kwargs.get("start") or 0, kwargs.get("page_length")
			return rows[start : start + length] if length else rows
		if doctype == "Employee":
			return [frappe._dict(name=e, company="Co", designation="Staff") for e in ("E1", "E2", "E3", "E4")]
		return []


class TestAttendanceConditions(unittest.TestCase):
	def test_nothing_selected_means_no_conditions(self):
		self.assertEqual(api._attendance_conditions(), {})
		self.assertEqual(api._attendance_conditions(0, 0, 0, "All"), {})
		self.assertEqual(api._attendance_conditions(None, "", "0", None), {})

	def test_each_choice_becomes_an_equality_condition(self):
		self.assertEqual(
			api._attendance_conditions(1, "1", True, "Half Day"),
			{"late_entry": 1, "early_exit": 1, "missing_checkout": 1, "status": "Half Day"},
		)

	def test_an_unknown_status_is_ignored_rather_than_sent_to_the_query(self):
		self.assertEqual(api._attendance_conditions(attendance_status="Whatever"), {})


class TestGalleryFilters(unittest.TestCase):
	def setUp(self):
		self.db = FakeDB()
		for target, kwargs in [
			("custom_hr.api._require_employee_gallery_access", {}),
			("custom_hr.api._get_accessible_employees", {"return_value": ["E1", "E2", "E3", "E4"]}),
			("frappe.get_all", {"side_effect": self.db.get_all}),
		]:
			p = patch(target, **kwargs)
			self.addCleanup(p.stop)
			p.start()

	def gallery(self, **kwargs):
		return api.get_employee_checkin_gallery(from_date=DATE, to_date=DATE, **kwargs)

	def names(self, result):
		return [row["name"] for row in result["rows"]]

	def test_late_only_keeps_every_log_of_a_late_day(self):
		result = self.gallery(late_entry=1)
		self.assertEqual(sorted(self.names(result)), ["C1", "C2", "C4"])
		self.assertEqual(result["has_more"], False)

	def test_early_only(self):
		self.assertEqual(sorted(self.names(self.gallery(early_exit=1))), ["C3", "C4"])

	def test_conditions_combine_on_the_same_attendance_row(self):
		self.assertEqual(self.names(self.gallery(late_entry=1, early_exit=1)), ["C4"])

	def test_status_and_missing_checkout(self):
		self.assertEqual(self.names(self.gallery(attendance_status="Half Day")), ["C5"])
		self.assertEqual(self.names(self.gallery(missing_checkout=1)), ["C5"])

	def test_the_late_flag_and_early_badge_data_stay_on_the_rows(self):
		row = self.gallery(early_exit=1)["rows"][0]
		self.assertIn(row["attendance_status"], ("Present",))
		self.assertEqual(row["early_exit"], 1)

	def test_pagination_applies_after_filtering(self):
		first = self.gallery(late_entry=1, page_length=2)
		self.assertEqual(len(first["rows"]), 2)
		self.assertEqual(first["has_more"], True)
		second = self.gallery(late_entry=1, page_length=2, start=2)
		self.assertEqual(len(second["rows"]), 1)
		self.assertEqual(second["has_more"], False)

	def test_no_matching_attendance_returns_empty_without_loading_checkins(self):
		result = self.gallery(attendance_status="On Leave")
		self.assertEqual(result, {"rows": [], "has_more": False})
		self.assertNotIn("Employee Checkin", [call[0] for call in self.db.calls])

	def test_without_attendance_filters_pagination_stays_in_the_database_query(self):
		self.gallery(page_length=3)
		checkin_call = next(call for call in self.db.calls if call[0] == "Employee Checkin")
		self.assertEqual(checkin_call[2]["page_length"], 4)

	def test_a_wide_range_with_attendance_filters_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			api.get_employee_checkin_gallery(from_date="2026-08-01", to_date=DATE, late_entry=1)


class TestSummaryFilters(unittest.TestCase):
	def setUp(self):
		self.db = FakeDB()
		self.employees = [frappe._dict(name="E1", employee_name="E1", company="Co", designation="Staff")]
		self.get_list_calls = []
		self.sql_rows = [
			frappe._dict(employee="E1", present=3, half_day=0, absent=0, on_leave=0, late=2, early=1, missing_checkout=1)
		]

		def get_list(doctype, **kwargs):
			self.get_list_calls.append(kwargs)
			return self.employees

		for target, kwargs in [
			("custom_hr.api._require_employee_gallery_access", {}),
			("frappe.get_all", {"side_effect": self.db.get_all}),
			("frappe.get_list", {"side_effect": get_list}),
			("frappe.db.sql", {"side_effect": lambda query, *a, **k: self.sql_rows if "tabAttendance" in query else []}),
		]:
			p = patch(target, **kwargs)
			self.addCleanup(p.stop)
			p.start()

	def summary(self, **kwargs):
		return api.get_attendance_summary_by_employee(from_date=DATE, to_date=DATE, **kwargs)

	def test_rows_carry_early_exit_and_missing_checkout_counts(self):
		row = self.summary()["rows"][0]
		self.assertEqual((row["late"], row["early"], row["missing_checkout"]), (2, 1, 1))

	def test_a_filter_limits_the_employee_list_to_those_with_a_matching_day(self):
		self.summary(late_entry=1)
		self.assertEqual(self.get_list_calls[0]["filters"]["name"], ["in", ["E1", "E3"]])

	def test_filters_combine_on_one_attendance_day(self):
		self.summary(late_entry=1, early_exit=1)
		self.assertEqual(self.get_list_calls[0]["filters"]["name"], ["in", ["E3"]])

	def test_no_matching_day_means_no_employees_and_no_employee_query(self):
		self.assertEqual(self.summary(attendance_status="On Leave"), {"rows": [], "has_more": False})
		self.assertEqual(self.get_list_calls, [])

	def test_without_filters_the_employee_list_is_not_narrowed(self):
		self.summary()
		self.assertNotIn("name", self.get_list_calls[0]["filters"])


class TestDailyCardFilters(unittest.TestCase):
	def setUp(self):
		self.db = FakeDB()
		for target, kwargs in [
			("custom_hr.api._require_employee_gallery_access", {}),
			("frappe.has_permission", {"return_value": True}),
			("frappe.get_all", {"side_effect": self.db.get_all}),
			("frappe.db.get_value", {"return_value": frappe._dict(employee_name="E1", company="Co", designation="Staff")}),
		]:
			p = patch(target, **kwargs)
			self.addCleanup(p.stop)
			p.start()

	def test_without_filters_every_day_is_returned(self):
		days = api.get_attendance_daily_cards("E1", DATE, DATE)["days"]
		self.assertEqual([day["date"] for day in days], [DATE])

	def test_days_that_do_not_match_are_dropped(self):
		self.assertEqual(api.get_attendance_daily_cards("E1", DATE, DATE, late_entry=1)["days"][0]["date"], DATE)
		self.assertEqual(api.get_attendance_daily_cards("E1", DATE, DATE, early_exit=1)["days"], [])
		self.assertEqual(api.get_attendance_daily_cards("E1", DATE, DATE, attendance_status="Absent")["days"], [])
