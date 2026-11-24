"""Master template resolution, duplicate guard, and replication rules for Salary Structure."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.services import salary_structure_template as svc


class TestSalaryStructureTemplate(unittest.TestCase):
	def test_resolve_prefix_prefers_explicit_field_then_name_prefix(self):
		self.assertEqual(svc.resolve_prefix(frappe._dict(name="Gaji Outlet - OUTLET A", template_prefix=None)), "Gaji Outlet")
		self.assertEqual(
			svc.resolve_prefix(frappe._dict(name="Gaji Outlet - MASTER-1", template_prefix=" Gaji Outlet ")),
			"Gaji Outlet",
		)
		self.assertEqual(svc.resolve_prefix(frappe._dict(name="Gaji Outlet - OUTLET A-2", template_prefix=None)), "Gaji Outlet")
		self.assertEqual(svc.resolve_prefix(frappe._dict(name="Gaji Khusus", template_prefix="")), "Gaji Khusus")

	def test_validate_template_blocks_duplicate_active_prefix(self):
		doc = frappe._dict(name="Gaji Outlet - B", is_master_template=1, docstatus=1, is_active="Yes", template_prefix=None)
		existing = [frappe._dict(name="Gaji Outlet - A", template_prefix=None)]
		with patch("frappe.get_all", return_value=existing):
			with self.assertRaisesRegex(frappe.ValidationError, "Gaji Outlet"):
				svc.validate_template(doc)

		other_prefix = [frappe._dict(name="Gaji Harian - A", template_prefix=None)]
		with patch("frappe.get_all", return_value=other_prefix):
			svc.validate_template(doc)  # different prefix passes cleanly

	def test_replicate_to_company_skips_if_already_exists_and_creates_when_missing(self):
		template = frappe._dict(
			name="Gaji Outlet - MASTER",
			template_prefix="Gaji Outlet",
			currency="IDR",
			payroll_frequency="Monthly",
			salary_slip_based_on_timesheet=0,
			is_default="No",
			earnings=[frappe._dict(salary_component="Gaji Pokok", formula="base", amount_based_on_formula=1)],
			deductions=[],
			employer_contributions=[],
			employee_benefits=[],
		)
		with patch("frappe.db.exists", return_value=True):
			self.assertIsNone(svc.replicate_to_company(template, "OUTLET A"))

		created = MagicMock()
		created.name = "Gaji Outlet - OUTLET B"
		with patch("frappe.db.exists", return_value=False), patch("frappe.new_doc", return_value=created):
			result = svc.replicate_to_company(template, "OUTLET B")
		self.assertEqual(result, "Gaji Outlet - OUTLET B")
		self.assertEqual((created.company, created.is_master_template, created.source_template), ("OUTLET B", 0, "Gaji Outlet - MASTER"))
		created.insert.assert_called_once_with(ignore_permissions=True)
		created.submit.assert_called_once()

	def test_sync_existing_child_never_overwrites_another_master(self):
		master = frappe._dict(name="Gaji Outlet - MASTER", earnings=[], deductions=[], employer_contributions=[], employee_benefits=[])
		other_master = frappe._dict(name="Gaji Outlet - OTHER", is_master_template=1, docstatus=1, is_active="Yes")
		with patch("frappe.get_doc", return_value=other_master):
			self.assertFalse(svc.sync_existing_child(master, "Gaji Outlet - OTHER"))

	def test_on_outlet_insert_replicates_all_active_masters(self):
		outlet = frappe._dict(name="OUTLET BARU")
		master_doc = frappe._dict(name="Gaji Outlet - MASTER")
		with (
			patch("frappe.db.exists", return_value=True),
			patch("frappe.get_all", return_value=["Gaji Outlet - MASTER"]),
			patch("frappe.get_doc", return_value=master_doc),
			patch.object(svc, "replicate_to_company") as replicate,
		):
			svc.on_outlet_insert(outlet)
		replicate.assert_called_once_with(master_doc, "OUTLET BARU")
