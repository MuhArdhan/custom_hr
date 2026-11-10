"""Attendance counts and the HR rates reach the Salary Slip for structure formulas."""

import unittest
from unittest.mock import patch

import frappe

from custom_hr.services import payroll_penalties as svc

DEFAULT = frappe._dict(for_company=None, potongan_telat=7000, potongan_pulang_cepat=5000, potongan_tidak_out=10000)
JURI = frappe._dict(for_company="JURI", potongan_telat=15000, potongan_pulang_cepat=0, potongan_tidak_out=10000)
RATES = frappe._dict(attendance_penalty_rates=[DEFAULT, JURI])


def day(late=0, early=0, missing=0, status="Present"):
	return frappe._dict(status=status, late_entry=late, early_exit=early, missing_checkout=missing)


def slip(**values):
	return frappe._dict(dict(docstatus=0, employee="EMP", company="Outlet A", start_date="2026-09-26", end_date="2026-10-25") | values)


class TestPayrollPenalties(unittest.TestCase):
	absent = 0

	def fill(self, doc, days, overtime=None):
		with (
			patch("frappe.get_all", return_value=days) as get_all,
			patch("frappe.get_cached_doc", return_value=RATES),
			patch("frappe.db.count", return_value=self.absent) as count,
			patch.object(svc, "paid_overtime", return_value=overtime or {}) as hours,
			patch.object(svc, "overtime_pay", return_value=12345) as pay,
		):
			svc.fill_attendance_penalties(doc)
		self.hours, self.pay, self.count = hours, pay, count
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

	def test_a_company_row_beats_the_default_row(self):
		doc = slip(company="JURI")
		self.fill(doc, [day(late=1)])
		self.assertEqual((doc.tarif_telat, doc.tarif_pulang_cepat, doc.tarif_tidak_out), (15000, 0, 10000))

	def test_without_any_matching_row_nothing_is_deducted(self):
		self.assertEqual(svc.rate_for([JURI], "Outlet A"), {})
		self.assertEqual(svc.rate_for([], "JURI"), {})

	def test_worked_days_count_a_half_day_as_half(self):
		doc = slip()
		self.fill(doc, [day(), day(status="Work From Home"), day(status="Half Day")])
		self.assertEqual(doc.jumlah_hadir, 2.5)

	def test_approved_overtime_hours_of_the_slip_period_add_up(self):
		doc = slip()
		overtime = {("EMP", "2026-10-01"): frappe._dict(hours=2, overtime_type="A"), ("EMP", "2026-10-02"): frappe._dict(hours=1.5, overtime_type="A")}
		self.fill(doc, [], overtime=overtime)
		self.assertEqual((doc.jam_lembur, doc.upah_lembur), (3.5, 12345))
		self.hours.assert_called_once_with("2026-09-26", "2026-10-25", "EMP")
		self.pay.assert_called_once_with("EMP", overtime, "2026-09-26", "2026-10-25")

	def test_only_recorded_absences_are_alpha(self):
		doc = slip()
		self.absent = 2
		self.fill(doc, [day()])
		self.assertEqual(doc.jumlah_alpha, 2)
		filters = self.count.call_args.args[1]
		self.assertEqual((filters["status"], filters["docstatus"]), ("Absent", 1))
		self.assertEqual(filters["attendance_date"], ["between", ["2026-09-26", "2026-10-25"]])

