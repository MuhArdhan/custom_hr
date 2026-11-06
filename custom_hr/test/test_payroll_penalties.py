"""Attendance counts and the HR rates reach the Salary Slip for structure formulas."""

import unittest
from unittest.mock import patch

import frappe

from custom_hr.services import payroll_penalties as svc

RATES = frappe._dict(potongan_telat=7000, potongan_pulang_cepat=5000, potongan_tidak_out=10000)


def day(late=0, early=0, missing=0):
	return frappe._dict(late_entry=late, early_exit=early, missing_checkout=missing)


def slip(**values):
	return frappe._dict(dict(docstatus=0, employee="EMP", start_date="2026-09-26", end_date="2026-10-25") | values)


class TestPayrollPenalties(unittest.TestCase):
	def fill(self, doc, days):
		with patch("frappe.get_all", return_value=days) as get_all, patch("frappe.get_cached_doc", return_value=RATES):
			svc.fill_attendance_penalties(doc)
		return get_all

	def test_counts_and_rates_land_on_the_slip(self):
		doc = slip()
		self.fill(doc, [day(late=1, missing=1), day(late=1, early=1), day()])
		self.assertEqual((doc.jumlah_telat, doc.jumlah_pulang_cepat, doc.jumlah_tidak_out), (2, 1, 1))
		self.assertEqual((doc.tarif_telat, doc.tarif_pulang_cepat, doc.tarif_tidak_out), (7000, 5000, 10000))

	def test_only_the_slip_period_and_worked_days_count(self):
		filters = self.fill(slip(), []).call_args.kwargs["filters"]
		self.assertEqual(filters["attendance_date"], ["between", ["2026-09-26", "2026-10-25"]])
		self.assertEqual(filters["status"], ["in", ("Present", "Half Day", "Work From Home")])
		self.assertEqual(filters["docstatus"], 1)

	def test_a_submitted_slip_keeps_what_it_was_paid_on(self):
		doc = slip(docstatus=1, jumlah_telat=3, tarif_telat=6000)
		self.assertFalse(self.fill(doc, [day(late=1)]).called)
		self.assertEqual((doc.jumlah_telat, doc.tarif_telat), (3, 6000))
