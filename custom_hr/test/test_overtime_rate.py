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

	def test_overtime_pay_groups_amounts_by_overtime_salary_component(self):
		reg = frappe._dict(FLAT, name="Lembur PH", overtime_salary_component="Lembur Reguler", hourly_rate=25000)
		hol = frappe._dict(FLAT, name="Lembur Holiday PH", overtime_salary_component="Lembur Holiday", hourly_rate=18750, weekend_multiplier=1)
		day2 = date(2026, 10, 2)
		overtime = {
			("EMP", DAY): frappe._dict(hours=2, overtime_type="Lembur PH"),
			("EMP", day2): frappe._dict(hours=4, overtime_type="Lembur Holiday PH"),
		}
		types = {"Lembur PH": reg, "Lembur Holiday PH": hol}
		with (
			patch("frappe.get_cached_doc", side_effect=lambda _dt, name: types[name]),
			patch("hrms.utils.holiday_list.get_holiday_dates_between_range", return_value=[]),
		):
			grouped = svc.overtime_pay_by_component("EMP", overtime, DAY, day2)
			total = svc.overtime_pay("EMP", overtime, DAY, day2)
		self.assertEqual(grouped, {"Lembur Reguler": 50000.0, "Lembur Holiday": 75000.0})
		self.assertEqual(total, 125000.0)

	def test_validate_overtime_type_requires_earning_and_warns_if_untaxed(self):
		doc = frappe._dict(overtime_salary_component="Kasbon")
		with patch("frappe.db.get_value", return_value=frappe._dict(type="Deduction", is_tax_applicable=0)):
			with patch("frappe.throw", side_effect=frappe.ValidationError):
				self.assertRaises(frappe.ValidationError, svc.validate_overtime_type, doc)

		doc = frappe._dict(overtime_salary_component="Lembur Khusus")
		with (
			patch("frappe.db.get_value", return_value=frappe._dict(type="Earning", is_tax_applicable=0)),
			patch("frappe.msgprint") as warn,
		):
			svc.validate_overtime_type(doc)
		warn.assert_called_once()

		with (
			patch("frappe.db.get_value", return_value=frappe._dict(type="Earning", is_tax_applicable=1)),
			patch("frappe.msgprint") as ok_msg,
		):
			svc.validate_overtime_type(doc)
		ok_msg.assert_not_called()
