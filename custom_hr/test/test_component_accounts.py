"""Akun Komponen Gaji: each company gets its own account with the listed number, a company row beats the default."""

import unittest

import frappe

from custom_hr.services.component_accounts import plan

ROWS = [
	frappe._dict(salary_component="Gaji Pokok", for_company=None, account_number="5120.001"),
	frappe._dict(salary_component="Gaji Pokok", for_company="JURI", account_number="5210.001"),
	frappe._dict(salary_component="Kasbon", for_company=None, account_number=" 1132.002 "),
]
ACCOUNTS = {
	("JURI", "5210.001"): "5210.001 - Biaya Gaji Staff - JURI",
	("JURI", "1132.002"): "1132.002 - Piutang Karyawan - JURI",
	("Outlet A", "5120.001"): "5120.001 - Biaya Gaji - OA",
	("Outlet A", "1132.002"): "1132.002 - Piutang Karyawan - OA",
	("Outlet B", "5120.001"): "5120.001 - Biaya Gaji - OB",
}


class TestComponentAccounts(unittest.TestCase):
	def test_each_company_gets_its_own_account_and_a_company_row_wins(self):
		wanted, _missing = plan(ROWS, ["JURI", "Outlet A", "Outlet B"], ACCOUNTS)
		self.assertEqual(
			wanted["Gaji Pokok"],
			{"JURI": "5210.001 - Biaya Gaji Staff - JURI", "Outlet A": "5120.001 - Biaya Gaji - OA", "Outlet B": "5120.001 - Biaya Gaji - OB"},
		)
		self.assertEqual(wanted["Kasbon"], {"JURI": "1132.002 - Piutang Karyawan - JURI", "Outlet A": "1132.002 - Piutang Karyawan - OA"})

	def test_a_company_without_the_number_is_reported_not_guessed(self):
		_wanted, missing = plan(ROWS, ["Outlet B"], ACCOUNTS)
		self.assertEqual(missing, [("Kasbon", "Outlet B", "1132.002")])

	def test_a_component_without_a_default_row_skips_other_companies(self):
		wanted, missing = plan(ROWS[1:2], ["JURI", "Outlet A"], ACCOUNTS)
		self.assertEqual((wanted, missing), ({"Gaji Pokok": {"JURI": "5210.001 - Biaya Gaji Staff - JURI"}}, []))
