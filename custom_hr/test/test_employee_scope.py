"""Outlet vs Non-Outlet/Department scope rules for Overtime Type, Leave Type, and Shift Type."""

import unittest
from unittest.mock import patch

import frappe

from custom_hr.services import employee_scope as scope


class TestEmployeeScope(unittest.TestCase):
	def test_matches_scope_handles_all_outlet_non_outlet_and_department(self):
		self.assertTrue(scope.matches_scope({"berlaku_untuk": "Semua"}, outlet="OUT-1", department=None))
		self.assertTrue(scope.matches_scope({"berlaku_untuk": "Semua"}, outlet=None, department="IT - ROPI"))

		self.assertTrue(scope.matches_scope({"berlaku_untuk": "Khusus Outlet"}, outlet="OUT-1"))
		self.assertFalse(scope.matches_scope({"berlaku_untuk": "Khusus Outlet"}, outlet=None, department="IT - ROPI"))

		self.assertFalse(scope.matches_scope({"berlaku_untuk": "Khusus Non-Outlet"}, outlet="OUT-1"))
		self.assertTrue(scope.matches_scope({"berlaku_untuk": "Khusus Non-Outlet"}, outlet=None, department="IT - ROPI"))

		jkt_rule = {"berlaku_untuk": "Khusus Non-Outlet", "hanya_department": "Jakarta - ROPI"}
		self.assertTrue(scope.matches_scope(jkt_rule, outlet=None, department="Jakarta - ROPI"))
		self.assertFalse(scope.matches_scope(jkt_rule, outlet=None, department="IT - ROPI"))

	def test_allowed_overtime_types_filters_out_mismatched_scope(self):
		rows = [
			frappe._dict(name="Lembur", max_hours=4.0, berlaku_untuk="Semua", hanya_department=None),
			frappe._dict(name="Lembur Outlet", max_hours=8.0, berlaku_untuk="Khusus Outlet", hanya_department=None),
			frappe._dict(name="Lembur JKT", max_hours=8.0, berlaku_untuk="Khusus Non-Outlet", hanya_department="Jakarta - ROPI"),
		]
		with patch("frappe.get_all", return_value=rows):
			self.assertEqual(
				[r["name"] for r in scope.allowed_overtime_types(outlet="OUT-1")],
				["Lembur", "Lembur Outlet"],
			)
			self.assertEqual(
				[r["name"] for r in scope.allowed_overtime_types(outlet=None, department="Jakarta - ROPI")],
				["Lembur", "Lembur JKT"],
			)
			self.assertEqual(
				[r["name"] for r in scope.allowed_overtime_types(outlet=None, department="IT - ROPI")],
				["Lembur"],
			)

	def test_filter_leave_types_keeps_only_matching_scope(self):
		rules = [
			frappe._dict(name="Cuti", berlaku_untuk="Semua", hanya_department=None),
			frappe._dict(name="Izin Outlet", berlaku_untuk="Khusus Outlet", hanya_department=None),
			frappe._dict(name="WFH Kantor", berlaku_untuk="Khusus Non-Outlet", hanya_department=None),
		]
		with patch("frappe.get_all", return_value=rules):
			self.assertEqual(
				scope.filter_leave_types(["Cuti", "Izin Outlet", "WFH Kantor"], outlet="OUT-1"),
				["Cuti", "Izin Outlet"],
			)
			self.assertEqual(
				scope.filter_leave_types(["Cuti", "Izin Outlet", "WFH Kantor"], outlet=None, department="IT - ROPI"),
				["Cuti", "WFH Kantor"],
			)

	def test_validate_leave_application_scope_blocks_mismatch(self):
		doc = frappe._dict(employee="EMP-1", leave_type="Izin Kantor", is_new=lambda: True, has_value_changed=lambda f: True)
		with (
			patch("frappe.db.get_value", return_value={"berlaku_untuk": "Khusus Non-Outlet", "hanya_department": None}),
			patch.object(scope, "employee_scope_info", return_value={"outlet": "OUT-1", "department": None}),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "tidak berlaku"):
				scope.validate_leave_application_scope(doc)

