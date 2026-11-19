"""Rekap Gaji Format Sheet: components sit in the sheet's column order, a combined column sums its components."""

import unittest

import frappe

from custom_hr.api.payroll_match import column_groups
from custom_hr.hrm.report.rekap_gaji_format_sheet import rekap_gaji_format_sheet as report

GROUPS = column_groups(
	[frappe._dict(excel_column=c, salary_component=s) for c, s in (("BF", "Uang Makan"), ("AO+AQ", "Upah Lembur"), ("AO+AQ", "Lembur Driver"), ("AL", "Gaji Pokok"))],
	set(),
)


class TestRekapGajiFormatSheet(unittest.TestCase):
	def test_components_follow_the_sheet_column_order(self):
		labels = [c["label"] for c in report.columns(GROUPS) if c["fieldtype"] == "Currency"][:3]
		self.assertEqual(labels, ["AL · Gaji Pokok", "AO+AQ · Upah Lembur + Lembur Driver", "BF · Uang Makan"])

	def test_a_row_sums_the_components_of_a_combined_column(self):
		slip = frappe._dict(name="SS-1", nip=123456.0, employee="EMP", net_pay=10)
		amounts = {"SS-1": {"Gaji Pokok": 3000000, "Upah Lembur": 100000, "Lembur Driver": 50000}}
		row = report.sheet_rows([slip], amounts, GROUPS)[0]
		self.assertEqual((row["nip"], row["AL"], row["AO+AQ"], row["BF"]), ("123456", 3000000, 150000, 0))
		self.assertNotIn("name", row)
