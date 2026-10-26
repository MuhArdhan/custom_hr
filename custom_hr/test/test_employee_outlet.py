"""A new Employee gets the Outlet that belongs to its Company (Outlets are named after the Company)."""

import unittest
from unittest.mock import patch

import frappe

from custom_hr.services.employee_outlet import fill_outlet


class TestEmployeeOutlet(unittest.TestCase):
	def run_hook(self, doc, outlets=("RS A",)):
		with patch("frappe.db.exists", side_effect=lambda doctype, name=None: name in outlets):
			fill_outlet(doc)
		return doc

	def test_empty_outlet_takes_the_company_outlet(self):
		self.assertEqual(self.run_hook(frappe._dict(company="RS A", outlet=None)).outlet, "RS A")

	def test_a_chosen_outlet_is_kept(self):
		self.assertEqual(self.run_hook(frappe._dict(company="RS A", outlet="RS B")).outlet, "RS B")

	def test_company_without_an_outlet_stays_empty(self):
		self.assertIsNone(self.run_hook(frappe._dict(company="JURI GROUP", outlet=None)).outlet)

	def test_no_company_does_nothing(self):
		self.assertIsNone(self.run_hook(frappe._dict(company=None, outlet=None)).outlet)
