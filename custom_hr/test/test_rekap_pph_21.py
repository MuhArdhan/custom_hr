"""Unit tests for Rekap PPh 21 Script Report."""

from __future__ import annotations

import unittest

import frappe

from custom_hr.hrm.report.rekap_pph_21 import rekap_pph_21 as rpt
from custom_hr.test.test_pph21_ter import make_settings


class TestRekapPPh21Report(unittest.TestCase):
	def _sample_slip(self):
		return frappe._dict(
			name="SS-001",
			employee="HR-EMP-0001",
			employee_name="Hasan Basri",
			company="PT. JUARA ROTI INDONESIA",
			department="PRODUKSI",
			designation="MANAGER",
			start_date="2026-09-26",
			end_date="2026-10-25",
			posting_date="2026-10-25",
			status="Submitted",
			docstatus=1,
			dasar_bpjs=10000000,
			dasar_bruto_pph21=0,
			tarif_ter_pph21=0,
			net_pay=9500000,
			nip=10123.0,
			nik="3275032207950028",
			passport_number="",
			gender="Male",
			marital_status="Married",
			dependents="1",
		)

	def test_builds_sheet_columns_ending_at_pph21_with_simulation(self):
		settings = make_settings(enable_pph21_ter=0)
		slips = [self._sample_slip()]
		details = {"SS-001": {"Gaji Pokok": 9000000, "Uang Makan": 400000, "Tunjangan Jabatan": 800000}}
		ordered = ["Gaji Pokok", "Uang Makan", "Tunjangan Jabatan"]

		cols, rows = rpt.build_report(slips, details, {}, ordered, settings, simulate=True)
		fieldnames = [c["fieldname"] for c in cols]
		self.assertIn("earn_gaji_pokok", fieldnames)
		self.assertIn("bpjs_jkk", fieldnames)
		self.assertEqual(fieldnames[-1], "pph21")

		row = rows[0]
		self.assertEqual(row["bulan"], "Oktober")
		self.assertEqual(row["nik"], "3275032207950028")
		self.assertEqual(row["nip"], "10123")
		self.assertEqual(row["gender"], "L")
		self.assertEqual(row["ptkp"], "K/1")
		self.assertEqual(row["ter_category"], "TER B")
		# Employer BPJS on 10M: 24,000 + 30,000 + 400,000 = 454,000 -> Bruto = 10,200,000 + 454,000 = 10,654,000 -> TER B 1.5%
		self.assertEqual(row["total_bpjs_perusahaan"], 454000.0)
		self.assertEqual(row["bruto_pph21"], 10654000.0)
		self.assertEqual(row["tarif_ter"], 1.5)
		self.assertEqual(row["pph21"], 159810.0)

	def test_normal_mode_respects_toggle_off(self):
		settings = make_settings(enable_pph21_ter=0)
		slips = [self._sample_slip()]
		details = {"SS-001": {"Gaji Pokok": 9000000}}
		_cols, rows = rpt.build_report(slips, details, {}, ["Gaji Pokok"], settings, simulate=False)
		row = rows[0]
		self.assertEqual(row["tarif_ter"], 0.0)
		self.assertEqual(row["pph21"], 0.0)
		self.assertEqual(row["ptkp"], "K/1")
