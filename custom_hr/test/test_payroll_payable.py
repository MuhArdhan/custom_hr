"""Auto-fill Payroll Payable Account on Salary Structure Assignment from Payroll Settings."""

import unittest
from unittest.mock import patch

import frappe

from custom_hr.services import payroll_payable


class TestPayrollPayableAccount(unittest.TestCase):
	def test_resolve_payable_account_strips_number_and_ignores_missing(self):
		with patch("frappe.db.get_value", return_value="2131.002 - Hutang Gaji - JURI") as lookup:
			self.assertEqual(
				payroll_payable.resolve_payable_account("PT. JUARA ROTI INDONESIA", " 2131.002 "),
				"2131.002 - Hutang Gaji - JURI",
			)
		lookup.assert_called_once_with(
			"Account",
			{"company": "PT. JUARA ROTI INDONESIA", "account_number": "2131.002", "is_group": 0},
			"name",
		)
		self.assertIsNone(payroll_payable.resolve_payable_account(None, "2131.002"))
		self.assertIsNone(payroll_payable.resolve_payable_account("JURI", "   "))

	def test_fill_payable_account_fills_when_blank_and_keeps_manual_value(self):
		doc = frappe._dict(company="OUTLET-A", payroll_payable_account=None)
		with patch.object(payroll_payable, "get_default_payable_account", return_value="2131.002 - Hutang Gaji - OA"):
			payroll_payable.fill_payable_account(doc)
		self.assertEqual(doc.payroll_payable_account, "2131.002 - Hutang Gaji - OA")

		manual = frappe._dict(company="OUTLET-A", payroll_payable_account="2131.001 - Biaya Yang Akan di Bayar - OA")
		with patch.object(payroll_payable, "get_default_payable_account", return_value="2131.002 - Hutang Gaji - OA") as getter:
			payroll_payable.fill_payable_account(manual)
		getter.assert_not_called()
		self.assertEqual(manual.payroll_payable_account, "2131.001 - Biaya Yang Akan di Bayar - OA")
