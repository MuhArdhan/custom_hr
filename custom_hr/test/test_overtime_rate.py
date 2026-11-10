"""Overtime is paid at the Overtime Type's fixed hourly rate times its day multiplier."""

import unittest
from datetime import date
from unittest.mock import patch

import frappe

from custom_hr.api import overtime_pay as svc

FLAT = frappe._dict(name="Lembur Outlet", overtime_calculation_method="Fixed Hourly Rate", hourly_rate=7500, standard_multiplier=1,
	applicable_for_weekend=1, weekend_multiplier=2, applicable_for_public_holiday=1, public_holiday_multiplier=3)
DAY = date(2026, 10, 1)


class TestOvertimeRate(unittest.TestCase):
	def pay(self, overtime_type, holidays=()):
		overtime = {("EMP", DAY): frappe._dict(hours=2, overtime_type=overtime_type.name)}
		with (
			patch("frappe.get_cached_doc", return_value=overtime_type),
			patch("hrms.utils.holiday_list.get_holiday_dates_between_range", return_value=list(holidays)),
		):
			return svc.overtime_pay("EMP", overtime, DAY, DAY)

	def test_a_normal_day_uses_the_standard_multiplier(self):
		self.assertEqual(self.pay(FLAT), 15000)

	def test_weekly_off_and_public_holiday_use_their_own_multiplier(self):
		self.assertEqual(self.pay(FLAT, [frappe._dict(holiday_date=DAY, weekly_off=1)]), 30000)
		self.assertEqual(self.pay(FLAT, [frappe._dict(holiday_date=DAY, weekly_off=0)]), 45000)

	def test_an_empty_multiplier_counts_as_one(self):
		self.assertEqual(self.pay(frappe._dict(FLAT, standard_multiplier=0)), 15000)

	def test_a_type_without_a_fixed_rate_stops_the_slip(self):
		with patch("frappe.throw", side_effect=frappe.ValidationError) as throw:
			self.assertRaises(frappe.ValidationError, self.pay, frappe._dict(FLAT, hourly_rate=0))
			self.assertRaises(frappe.ValidationError, self.pay, frappe._dict(FLAT, overtime_calculation_method="Salary Component Based"))
		self.assertEqual(throw.call_count, 2)

	def test_no_overtime_pays_nothing(self):
		self.assertEqual(svc.overtime_pay("EMP", {}, DAY, DAY), 0)
