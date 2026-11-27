"""Tests for cross-company Salary Structure scoping via Employee.outlet and Department."""

import unittest
from unittest.mock import patch

import frappe

from custom_hr.services import salary_structure_scope as svc


class TestSalaryStructureScope(unittest.TestCase):
	def test_validate_salary_structure_clears_dept_for_outlet_and_forbids_payment_account(self):
		doc = frappe._dict(berlaku_untuk="Khusus Outlet", hanya_department="Produksi", lintas_company=1, payment_account="BCA - X")
		with self.assertRaises(frappe.ValidationError):
			svc.validate_salary_structure(doc)
		self.assertIsNone(doc.hanya_department)

		clean = frappe._dict(berlaku_untuk="Khusus Outlet", hanya_department="Produksi", lintas_company=1, payment_account=None)
		svc.validate_salary_structure(clean)
		self.assertIsNone(clean.hanya_department)

	def test_validate_assignment_scope_allows_lintas_company_and_enforces_outlet_placement(self):
		outlet_ss = frappe._dict(company="PT. JUARA ROTI INDONESIA", lintas_company=1, berlaku_untuk="Khusus Outlet", hanya_department=None)
		ph_ss = frappe._dict(company="PT. JUARA ROTI INDONESIA", lintas_company=0, berlaku_untuk="Khusus Non-Outlet", hanya_department="Produksi")

		# Outlet employee in another Company allowed on lintas_company Khusus Outlet structure
		assignment = frappe._dict(employee="EMP-OUT", company="RS PKU", salary_structure="Gaji Outlet")
		with (
			patch("frappe.db.get_value", return_value=outlet_ss),
			patch.object(svc, "employee_scope_info", return_value=frappe._dict(outlet="RS PKU", department=None, company="RS PKU")),
		):
			svc.validate_assignment_scope(assignment)

		# PH employee (no outlet) blocked from Khusus Outlet structure
		ph_assignment = frappe._dict(employee="EMP-PH", company="PT. JUARA ROTI INDONESIA", salary_structure="Gaji Outlet")
		with (
			patch("frappe.db.get_value", return_value=outlet_ss),
			patch.object(svc, "employee_scope_info", return_value=frappe._dict(outlet=None, department="Produksi", company="PT. JUARA ROTI INDONESIA")),
			self.assertRaises(frappe.ValidationError),
		):
			svc.validate_assignment_scope(ph_assignment)

		# Different company blocked when lintas_company = 0
		cross_co = frappe._dict(employee="EMP-OUT", company="RS PKU", salary_structure="Gaji PH")
		with (
			patch("frappe.db.get_value", return_value=ph_ss),
			patch.object(svc, "employee_scope_info", return_value=frappe._dict(outlet=None, department="Produksi", company="RS PKU")),
			self.assertRaises(frappe.ValidationError),
		):
			svc.validate_assignment_scope(cross_co)

		# Department restriction respected for Non-Outlet employee
		dept_mismatch = frappe._dict(employee="EMP-PH-FIN", company="PT. JUARA ROTI INDONESIA", salary_structure="Gaji PH")
		with (
			patch("frappe.db.get_value", return_value=ph_ss),
			patch.object(svc, "employee_scope_info", return_value=frappe._dict(outlet=None, department="Finance", company="PT. JUARA ROTI INDONESIA")),
			self.assertRaises(frappe.ValidationError),
		):
			svc.validate_assignment_scope(dept_mismatch)

	def test_salary_structure_query_filters_by_outlet_and_lintas_company(self):
		rows = [
			frappe._dict(name="Gaji PH", company="PT. JUARA ROTI INDONESIA", lintas_company=1, berlaku_untuk="Khusus Non-Outlet", hanya_department=None),
			frappe._dict(name="Gaji Outlet", company="PT. JUARA ROTI INDONESIA", lintas_company=1, berlaku_untuk="Khusus Outlet", hanya_department=None),
			frappe._dict(name="Gaji Harian Outlet", company="PT. JUARA ROTI INDONESIA", lintas_company=1, berlaku_untuk="Khusus Outlet", hanya_department=None),
			frappe._dict(name="Gaji Cabang Lokal", company="OUTLET LAIN", lintas_company=0, berlaku_untuk="Khusus Outlet", hanya_department=None),
		]
		with (
			patch("frappe.get_all", return_value=rows),
			patch("frappe.db.exists", side_effect=lambda dt, name: dt == "DocType" or (dt == "Outlet" and name == "RS PKU")),
			patch.object(svc, "employee_scope_info", return_value=frappe._dict(outlet="RS PKU", department=None, company="RS PKU")),
		):
			outlet_emp_res = svc.salary_structure_query("Salary Structure", "", "name", 0, 20, {"company": "RS PKU", "employee": "EMP-1"})
			self.assertEqual(outlet_emp_res, [("Gaji Outlet",), ("Gaji Harian Outlet",)])

			outlet_bulk_res = svc.salary_structure_query("Salary Structure", "", "name", 0, 20, {"company": "RS PKU"})
			self.assertEqual(outlet_bulk_res, [("Gaji Outlet",), ("Gaji Harian Outlet",)])

		with (
			patch("frappe.get_all", return_value=rows),
			patch("frappe.db.exists", side_effect=lambda dt, name: dt == "DocType"),
			patch.object(svc, "employee_scope_info", return_value=frappe._dict(outlet=None, department="Produksi", company="PT. JUARA ROTI INDONESIA")),
		):
			ph_res = svc.salary_structure_query("Salary Structure", "", "name", 0, 20, {"company": "PT. JUARA ROTI INDONESIA", "employee": "EMP-PH"})
			self.assertEqual(ph_res, [("Gaji PH",)])
