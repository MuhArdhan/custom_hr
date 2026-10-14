import json
import unittest
from unittest.mock import patch

import frappe

from custom_hr.overrides.salary_slip import (
	AttendancePayrollMixin,
	deduction_amounts,
	validate_deduction_amounts,
)


class NativeStub:
	def calculate_net_pay(self, *args, **kwargs):
		return "native totals"

	def add_structure_component(self, row, component_type):
		return "native component"

	def update_component_row(self, row, amount, component_type, **kwargs):
		self.updated = (row.salary_component, amount, component_type, kwargs)


class SlipStub(AttendancePayrollMixin, NativeStub):
	def __init__(self):
		self.docstatus = 0
		self.employee = "EMP"
		self.start_date = "2026-10-01"
		self.end_date = "2026-10-31"
		self.salary_structure = "Structure"
		self.deductions = []
		self.custom_hr_attendance_snapshot = None
		self.data = {}
		self.default_data = {}

	def get(self, key, default=None):
		return getattr(self, key, default)

	def set(self, key, value):
		setattr(self, key, value)


class TestAttendanceSalarySlip(unittest.TestCase):
	def setUp(self):
		rounding = patch("frappe.utils.data.rounded", side_effect=lambda value, precision, method=None: round(value, precision))
		rounding.start()
		self.addCleanup(rounding.stop)
		clock = patch("custom_hr.overrides.salary_slip.now_datetime", return_value="2026-10-14 10:00:00")
		clock.start()
		self.addCleanup(clock.stop)

	def summary(self):
		return {"managed_components": ["Alpha"], "rows": [
			{"category": "Alpha", "salary_component": "Alpha", "quantity": 1, "unit": "Hari",
				"estimated_amount": 150000, "source_details": "[]", "managed_by_attendance": True}],
			"source_hash": "hash", "warnings": [], "blockers": []}

	def test_amounts_group_multiple_units_for_same_component(self):
		summary = self.summary()
		summary["rows"].append({"salary_component": "Alpha", "estimated_amount": 50000})
		summary["rows"].append({"salary_component": "Other", "estimated_amount": 99999})
		self.assertEqual(deduction_amounts(summary), {"Alpha": 200000})

	def test_calculation_sets_snapshot_before_native_totals(self):
		doc = SlipStub()
		with patch("custom_hr.overrides.salary_slip.collect_summary", return_value=self.summary()):
			with patch.object(doc, "_validate_attendance_structure"):
				self.assertEqual(doc.calculate_net_pay(), "native totals")
		self.assertEqual(doc._attendance_amounts, {"Alpha": 150000})
		self.assertEqual(json.loads(doc.custom_hr_attendance_snapshot), self.summary()["rows"])

	def test_no_enabled_rules_keeps_native_components(self):
		doc = SlipStub()
		summary = self.summary()
		summary["managed_components"] = []
		with patch("custom_hr.overrides.salary_slip.collect_summary", return_value=summary):
			doc.calculate_net_pay()
		self.assertFalse(doc._attendance_amounts)
		self.assertIsNone(doc.custom_hr_attendance_snapshot)

	def test_managed_component_updates_existing_native_row(self):
		doc = SlipStub()
		doc._attendance_amounts = {"Alpha": 150000}
		doc.add_structure_component(frappe._dict(salary_component="Alpha", abbr="ALP"), "deductions")
		self.assertEqual(doc.updated[:3], ("Alpha", 150000, "deductions"))
		self.assertEqual(doc.data["ALP"], 150000)
		self.assertFalse(doc.updated[3]["remove_if_zero_valued"])

	def test_unmanaged_component_keeps_native_formula(self):
		doc = SlipStub()
		doc._attendance_amounts = {"Alpha": 150000}
		self.assertEqual(doc.add_structure_component(
			frappe._dict(salary_component="BPJS"), "deductions"), "native component")

	def test_managed_component_rejects_formula_conflict(self):
		doc = SlipStub()
		doc._attendance_amounts = {"Alpha": 150000}
		with patch.object(frappe, "throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				doc.add_structure_component(frappe._dict(salary_component="Alpha", formula="base / 22"), "deductions")

	def test_submitted_snapshot_does_not_read_new_sources(self):
		doc = SlipStub()
		doc.docstatus = 1
		doc.custom_hr_attendance_snapshot = json.dumps(self.summary()["rows"])
		with patch("custom_hr.overrides.salary_slip.collect_summary") as collect:
			doc.calculate_net_pay()
			collect.assert_not_called()
		self.assertEqual(doc._attendance_amounts, {"Alpha": 150000})

	def test_changed_deduction_blocks_submission(self):
		doc = SlipStub()
		doc.deductions = [frappe._dict(salary_component="Alpha", amount=1)]
		with patch.object(frappe, "throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				validate_deduction_amounts(doc, self.summary())

	def test_duplicate_deduction_blocks_submission(self):
		doc = SlipStub()
		doc.deductions = [frappe._dict(salary_component="Alpha", amount=150000)] * 2
		with patch.object(frappe, "throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				validate_deduction_amounts(doc, self.summary())

	def test_missing_structure_component_is_rejected(self):
		doc = SlipStub()
		doc._attendance_amounts = {"Alpha": 150000}
		with patch.object(frappe, "get_cached_doc", return_value=frappe._dict(deductions=[])):
			with patch.object(frappe, "throw", side_effect=ValueError):
				with self.assertRaises(ValueError):
					doc._validate_attendance_structure(self.summary())
