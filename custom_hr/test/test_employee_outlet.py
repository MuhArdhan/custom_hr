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


class TestCurrentEmployeeInfo(unittest.TestCase):
	def test_the_app_learns_the_employees_outlet(self):
		from custom_hr.services import employee_outlet

		with patch("hrms.api.get_current_employee_info", return_value={"name": "EMP-1"}), patch("frappe.db.get_value", return_value="Outlet A") as read:
			info = employee_outlet.get_current_employee_info()
		self.assertEqual(info, {"name": "EMP-1", "outlet": "Outlet A"})
		self.assertEqual(read.call_args.args[:3], ("Employee", "EMP-1", "outlet"))

	def test_no_employee_stays_empty(self):
		from custom_hr.services import employee_outlet

		with patch("hrms.api.get_current_employee_info", return_value={}):
			self.assertEqual(employee_outlet.get_current_employee_info(), {})

	def test_the_hrms_method_is_overridden(self):
		self.assertEqual(frappe.get_hooks("override_whitelisted_methods")["hrms.api.get_current_employee_info"][-1], "custom_hr.services.employee_outlet.get_current_employee_info")
