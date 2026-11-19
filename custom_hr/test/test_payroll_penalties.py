"""Attendance counts and the HR rates reach the Salary Slip for structure formulas."""

import unittest
from unittest.mock import patch

import frappe

from custom_hr.services import payroll_penalties as svc

DEFAULT = frappe._dict(for_company=None, potongan_telat=7000, potongan_pulang_cepat=5000, potongan_tidak_out=10000)
JURI = frappe._dict(for_company="JURI", potongan_telat=15000, potongan_pulang_cepat=0, potongan_tidak_out=10000)
SHIFTS = [frappe._dict(shift_type="Pagi", tunjangan=8000), frappe._dict(shift_type="Siang", tunjangan=12000)]
DAILY = [
	frappe._dict(for_company=None, for_department=None, uang_makan=31000, transport=0),
	frappe._dict(for_company="JURI", for_department=None, uang_makan=20000, transport=22000),
	frappe._dict(for_company="JURI", for_department="Jakarta", uang_makan=30000, transport=22000),
]
PARENTS = {"Produksi Jakarta": ["Jakarta", "All Departments"], "Jakarta": ["All Departments"], "Klaten": ["All Departments"]}
JOBS = [
	frappe._dict(designation="SPV", tunjangan_jabatan=500000, tunjangan_resiko=0),
	frappe._dict(designation="Driver", tunjangan_jabatan=0, tunjangan_resiko=100000),
]
RATES = frappe._dict(attendance_penalty_rates=[DEFAULT, JURI], shift_allowances=SHIFTS, daily_rates=DAILY, designation_allowances=JOBS)


def day(late=0, early=0, missing=0, status="Present", shift=None, leave_type=None):
	return frappe._dict(
		status=status, late_entry=late, early_exit=early, missing_checkout=missing, shift=shift, leave_type=leave_type
	)


# desk value HR keeps: "counts as present" per Leave Type
DESK = {("Leave Type", "Cuti", "dihitung_hadir"): 1}


def slip(**values):
	return frappe._dict(dict(docstatus=0, employee="EMP", company="Outlet A", start_date="2026-09-26", end_date="2026-10-25") | values)


class TestPayrollPenalties(unittest.TestCase):
	absent = 0

	def fill(self, doc, days, overtime=None):
		with (
			patch("frappe.get_all", return_value=days) as get_all,
			patch("frappe.get_cached_doc", return_value=RATES),
			patch("frappe.get_cached_value", side_effect=lambda dt, name, field: DESK.get((dt, name, field))),
			patch("frappe.db.count", return_value=self.absent) as count,
			patch.object(svc, "paid_overtime", return_value=overtime or {}) as hours,
			patch.object(svc, "overtime_pay", return_value=12345) as pay,
			patch.object(svc, "izin_hours", return_value=3.5) as izin,
		):
			svc.fill_attendance_penalties(doc)
		self.hours, self.pay, self.count, self.izin = hours, pay, count, izin
		return get_all

	def test_counts_and_rates_land_on_the_slip(self):
		doc = slip()
		self.fill(doc, [day(late=1, missing=1), day(late=1, early=1), day()])
		self.assertEqual((doc.jumlah_telat, doc.jumlah_pulang_cepat, doc.jumlah_tidak_out), (2, 1, 1))
		self.assertEqual((doc.tarif_telat, doc.tarif_pulang_cepat, doc.tarif_tidak_out), (7000, 5000, 10000))

	def test_only_the_slip_period_and_worked_days_count(self):
		filters = self.fill(slip(), []).call_args.kwargs["filters"]
		self.assertEqual(filters["attendance_date"], ["between", ["2026-09-26", "2026-10-25"]])
		self.assertEqual(filters["status"], ["in", ("Present", "Half Day", "Work From Home", "On Leave")])
		self.assertEqual(filters["docstatus"], 1)

	def test_a_submitted_slip_keeps_what_it_was_paid_on(self):
		doc = slip(docstatus=1, jumlah_telat=3, tarif_telat=6000)
		self.assertFalse(self.fill(doc, [day(late=1)]).called)
		self.assertEqual((doc.jumlah_telat, doc.tarif_telat), (3, 6000))

	def test_a_company_row_beats_the_default_row(self):
		doc = slip(company="JURI")
		self.fill(doc, [day(late=1)])
		self.assertEqual((doc.tarif_telat, doc.tarif_pulang_cepat, doc.tarif_tidak_out), (15000, 0, 10000))

	def test_daily_rates_take_the_most_specific_row(self):
		cases = (
			("JURI", "Jakarta", (30000, 22000)),
			("JURI", "Produksi Jakarta", (30000, 22000)),
			("JURI", "Klaten", (20000, 22000)),
			("JURI", None, (20000, 22000)),
			("Outlet A", None, (31000, 0)),
		)
		for company, department, expected in cases:
			doc = slip(company=company, department=department)
			with patch.object(svc, "get_ancestors_of", side_effect=lambda dt, name: PARENTS[name]):
				self.fill(doc, [])
			self.assertEqual((doc.tarif_uang_makan, doc.tarif_transport), expected)
		self.assertEqual(svc.daily_rate_for(DAILY[1:], "Outlet A", []), {})

	def bpjs(self, ssa, out=0):
		settings = frappe._dict(
			daily_rates=[frappe._dict(for_company="JURI", for_department=None, uang_makan=20000, transport=22000, hari_bpjs=21)],
			bpjs_rates=[frappe._dict(kode="iuran_ks", persen=1, batas_atas=12000000), frappe._dict(kode="iuran_tk", persen=2, batas_atas=0)],
		)
		doc = slip(company="JURI", department=None)
		with patch("frappe.get_cached_doc", return_value=settings), patch("frappe.get_cached_value", return_value=out):
			return svc.bpjs_values(doc, frappe._dict(ssa))

	def test_bpjs_base_is_gp_plus_the_days_of_meal_and_transport(self):
		self.assertEqual(self.bpjs({"base": 3000000, "variable": 0}), {"dasar_bpjs": 3882000, "iuran_ks": 38820, "iuran_tk": 77640})

	def test_a_typed_variable_is_the_bpjs_base(self):
		self.assertEqual(self.bpjs({"base": 3000000, "variable": 4000000})["dasar_bpjs"], 4000000)

	def test_the_cap_limits_only_its_own_rate(self):
		values = self.bpjs({"base": 20000000, "variable": 0})
		self.assertEqual((values["iuran_ks"], values["iuran_tk"]), (120000, 417640))

	def test_an_employee_outside_bpjs_pays_nothing(self):
		self.assertEqual(self.bpjs({"base": 3000000, "variable": 3882000}, out=1), {"dasar_bpjs": 0, "iuran_ks": 0, "iuran_tk": 0})

	def test_working_days_are_the_mondays_to_fridays_of_the_period(self):
		self.assertEqual(svc.working_days("2026-08-26", "2026-09-25"), 23)
		self.assertEqual(svc.working_days("2026-09-26", "2026-10-25"), 20)
		doc = slip()
		self.fill(doc, [])
		self.assertEqual(doc.hari_kerja, 20)

	def test_without_any_matching_row_nothing_is_deducted(self):
		self.assertEqual(svc.rate_for([JURI], "Outlet A"), {})
		self.assertEqual(svc.rate_for([], "JURI"), {})

	def test_worked_days_count_a_half_day_as_half(self):
		doc = slip()
		self.fill(doc, [day(), day(status="Work From Home"), day(status="Half Day")])
		self.assertEqual(doc.jumlah_hadir, 2.5)

	def test_leave_counts_as_present_only_when_its_leave_type_is_ticked(self):
		doc = slip()
		self.fill(doc, [day(), day(status="On Leave", leave_type="Cuti"), day(status="On Leave", leave_type="Sakit")])
		self.assertEqual(doc.jumlah_hadir, 2)

	def test_shift_allowance_adds_each_worked_day_of_a_listed_shift(self):
		doc = slip()
		days = [day(shift="Pagi"), day(shift="Pagi"), day(shift="Siang"), day(shift="Kantor"), day(), day(status="On Leave", leave_type="Cuti", shift="Pagi")]
		self.fill(doc, days)
		self.assertEqual(doc.tunjangan_shift, 28000)

	def test_allowances_follow_the_designation_and_are_zero_without_one(self):
		for designation, expected in (("SPV", (500000, 0)), ("Driver", (0, 100000)), ("Staf", (0, 0)), (None, (0, 0))):
			doc = slip(designation=designation)
			self.fill(doc, [])
			self.assertEqual((doc.tunjangan_jabatan, doc.tunjangan_resiko), expected, designation)

	def test_approved_overtime_hours_of_the_slip_period_add_up(self):
		doc = slip()
		overtime = {("EMP", "2026-10-01"): frappe._dict(hours=2, overtime_type="A"), ("EMP", "2026-10-02"): frappe._dict(hours=1.5, overtime_type="A")}
		self.fill(doc, [], overtime=overtime)
		self.assertEqual((doc.jam_lembur, doc.upah_lembur), (3.5, 12345))
		self.hours.assert_called_once_with("2026-09-26", "2026-10-25", "EMP")
		self.pay.assert_called_once_with("EMP", overtime, "2026-09-26", "2026-10-25")

	def test_approved_hourly_leave_of_the_slip_period_lands_as_jam_izin(self):
		doc = slip()
		self.fill(doc, [])
		self.assertEqual(doc.jam_izin, 3.5)
		self.izin.assert_called_once_with("EMP", "2026-09-26", "2026-10-25")

	def test_only_recorded_absences_are_alpha(self):
		doc = slip()
		self.absent = 2
		self.fill(doc, [day()])
		self.assertEqual(doc.jumlah_alpha, 2)
		filters = self.count.call_args.args[1]
		self.assertEqual((filters["status"], filters["docstatus"]), ("Absent", 1))
		self.assertEqual(filters["attendance_date"], ["between", ["2026-09-26", "2026-10-25"]])

