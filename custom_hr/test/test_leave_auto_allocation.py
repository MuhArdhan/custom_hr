"""Leave Type auto allocation: period maths, validation and the allocation job (rolled back by the runner)."""

import unittest
from datetime import date
from unittest.mock import patch

import frappe

from custom_hr.services.leave_auto_allocation import allocate, period_for, validate_leave_type

TYPE = "_Test Auto Izin Sakit"


class TestPeriodFor(unittest.TestCase):
	def test_monthly_from_the_first(self):
		self.assertEqual(period_for("2026-10-30", "Monthly", 1), (date(2026, 10, 1), date(2026, 10, 31)))
		self.assertEqual(period_for("2026-02-01", "Monthly", 1), (date(2026, 2, 1), date(2026, 2, 28)))

	def test_monthly_cutoff_crosses_months_and_years(self):
		self.assertEqual(period_for("2026-10-21", "Monthly", 21), (date(2026, 10, 21), date(2026, 11, 20)))
		self.assertEqual(period_for("2026-10-20", "Monthly", 21), (date(2026, 9, 21), date(2026, 10, 20)))
		self.assertEqual(period_for("2027-01-05", "Monthly", 21), (date(2026, 12, 21), date(2027, 1, 20)))

	def test_quarterly_and_yearly_align_to_january(self):
		self.assertEqual(period_for("2026-11-15", "Quarterly", 1), (date(2026, 10, 1), date(2026, 12, 31)))
		self.assertEqual(period_for("2026-01-10", "Quarterly", 21), (date(2025, 10, 21), date(2026, 1, 20)))
		self.assertEqual(period_for("2026-06-30", "Yearly", 1), (date(2026, 1, 1), date(2026, 12, 31)))


class TestAllocate(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		self.leave_type = frappe.get_doc({
			"doctype": "Leave Type", "leave_type_name": TYPE, "auto_allocate": 1,
			"auto_allocate_every": "Monthly", "auto_allocate_leaves": 2, "auto_allocate_start_day": 1,
		})
		with patch("frappe.enqueue"):
			self.leave_type.insert()
		self.active = frappe.get_all("Employee", filters={"status": "Active", "date_of_joining": ["<=", "2026-10-31"]}, or_filters=[["relieving_date", "is", "not set"], ["relieving_date", ">=", "2026-10-01"]], pluck="name")
		self.assertTrue(self.active, "needs at least one active employee on the site")

	def allocations(self):
		return frappe.get_all("Leave Allocation", filters={"leave_type": TYPE, "docstatus": 1}, fields=["employee", "from_date", "to_date", "new_leaves_allocated"])

	def test_every_active_employee_gets_one_period_and_a_rerun_adds_nothing(self):
		created = allocate(today=date(2026, 10, 15), leave_type=TYPE)
		self.assertEqual(sorted(employee for employee, _ in created), sorted(self.active))
		rows = self.allocations()
		self.assertTrue(all((r.from_date, r.to_date, r.new_leaves_allocated) == (date(2026, 10, 1), date(2026, 10, 31), 2) for r in rows))
		self.assertEqual(allocate(today=date(2026, 10, 20), leave_type=TYPE), [])

	def test_next_period_is_a_new_allocation(self):
		allocate(today=date(2026, 10, 15), leave_type=TYPE)
		allocate(today=date(2026, 11, 1), leave_type=TYPE)
		periods = {(r.from_date, r.to_date) for r in self.allocations()}
		self.assertEqual(periods, {(date(2026, 10, 1), date(2026, 10, 31)), (date(2026, 11, 1), date(2026, 11, 30))})

	def test_applies_to_splits_outlet_and_non_outlet_employees(self):
		outlet = {e.name for e in frappe.get_all("Employee", filters={"name": ["in", self.active], "outlet": ["is", "set"]})}
		for applies_to, expected in (("Outlet", outlet), ("Non-Outlet", set(self.active) - outlet)):
			with self.subTest(applies_to):
				frappe.db.delete("Leave Allocation", {"leave_type": TYPE})
				frappe.db.set_value("Leave Type", TYPE, "auto_allocate_for", applies_to)
				self.assertEqual({employee for employee, _ in allocate(today=date(2026, 10, 15), leave_type=TYPE)}, expected)

	def test_disabled_type_is_skipped(self):
		self.leave_type.auto_allocate = 0
		self.leave_type.save()
		self.assertEqual(allocate(today=date(2026, 10, 15), leave_type=TYPE), [])

	def test_invalid_settings_are_rejected(self):
		for changes in ({"auto_allocate_leaves": 0}, {"auto_allocate_start_day": 29}, {"is_lwp": 1}, {"auto_allocate_for": "Outlets"}):
			doc = frappe.copy_doc(self.leave_type)
			doc.update(changes)
			with self.subTest(changes), self.assertRaises(frappe.ValidationError):
				validate_leave_type(doc)
