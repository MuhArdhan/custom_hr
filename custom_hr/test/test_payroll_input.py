"""Payroll period input: the 26-25 period and what saving one cell does to its Additional Salary."""

import unittest
from datetime import date
from unittest.mock import patch

import frappe

from custom_hr.api.payroll_input import period_bounds, plan_cell


class TestPayrollInput(unittest.TestCase):
	def test_period_runs_from_the_26th_to_the_25th(self):
		self.assertEqual(period_bounds("2026-10"), (date(2026, 9, 26), date(2026, 10, 25)))
		self.assertEqual(period_bounds("2026-01"), (date(2025, 12, 26), date(2026, 1, 25)))
		self.assertEqual(period_bounds("2026-03"), (date(2026, 2, 26), date(2026, 3, 25)))
		with patch("frappe.throw", side_effect=frappe.ValidationError), self.assertRaises(frappe.ValidationError):
			period_bounds("")

	def test_a_cell_creates_replaces_cancels_or_keeps(self):
		self.assertEqual(plan_cell([], 50000), "create")
		self.assertEqual(plan_cell([], 0), "keep")
		self.assertEqual(plan_cell([50000], 50000), "keep")
		self.assertEqual(plan_cell([50000], 75000), "replace")
		self.assertEqual(plan_cell([50000], 0), "cancel")
		self.assertEqual(plan_cell([50000], None), "cancel")

	def test_a_cell_with_several_entries_is_never_touched(self):
		self.assertEqual(plan_cell([20000, 30000], 50000), "locked")
		self.assertEqual(plan_cell([20000, 30000], 0), "locked")
