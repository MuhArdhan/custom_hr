"""Create User Permission restricts the Employee only: the Company is never locked, an old Company lock goes on save."""

import unittest
from unittest.mock import patch

import frappe

from custom_hr.overrides.employee import CustomEmployee

MODULE = "custom_hr.overrides.employee"


def employee(create_user_permission=1):
	doc = frappe.get_doc({"doctype": "Employee", "first_name": "Budi", "company": "PT Kantor", "user_id": "budi@example.com"})
	doc.name, doc.create_user_permission = "EMP-1", create_user_permission
	return doc


class TestEmployeeUserPermission(unittest.TestCase):
	def run_hook(self, doc, existing):
		"""`existing`: the (allow, for_value) User Permissions the user already has."""
		with patch("frappe.db.exists", side_effect=lambda dt, filters: (filters["allow"], filters["for_value"]) in existing), \
			patch(f"{MODULE}.add_user_permission") as add, patch(f"{MODULE}.remove_user_permission") as remove:
			doc.update_user_permissions()
		return [call.args[:3] for call in add.call_args_list], [call.args[:3] for call in remove.call_args_list]

	def test_linking_a_user_restricts_the_employee_only(self):
		added, removed = self.run_hook(employee(), existing=set())
		self.assertEqual(added, [("Employee", "EMP-1", "budi@example.com")])
		self.assertEqual(removed, [])

	def test_saving_again_drops_the_company_lock_erpnext_made_before(self):
		added, removed = self.run_hook(employee(), existing={("Employee", "EMP-1"), ("Company", "PT Kantor")})
		self.assertEqual(added, [])
		self.assertEqual(removed, [("Company", "PT Kantor", "budi@example.com")])

	def test_unticking_removes_both_locks(self):
		_, removed = self.run_hook(employee(create_user_permission=0), existing={("Employee", "EMP-1"), ("Company", "PT Kantor")})
		self.assertEqual(sorted(removed), [("Company", "PT Kantor", "budi@example.com"), ("Employee", "EMP-1", "budi@example.com")])

	def test_it_replaces_the_hrms_employee_class(self):
		from hrms.overrides.employee_master import EmployeeMaster

		self.assertTrue(issubclass(CustomEmployee, EmployeeMaster))
		self.assertEqual(frappe.get_hooks("override_doctype_class")["Employee"][-1], "custom_hr.overrides.employee.CustomEmployee")
		self.assertIsInstance(employee(), CustomEmployee)
