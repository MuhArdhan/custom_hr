"""Bulk Deduct from Salary for paid Employee Advances."""

import unittest
from datetime import date
from unittest.mock import patch

import frappe

from custom_hr.api import advance_bulk as svc


class TestAdvanceBulk(unittest.TestCase):
	def test_default_payroll_date_uses_25th_cutoff(self):
		self.assertEqual(svc._default_payroll_date(date(2026, 10, 15)), date(2026, 10, 25))
		self.assertEqual(svc._default_payroll_date(date(2026, 10, 25)), date(2026, 10, 25))
		self.assertEqual(svc._default_payroll_date(date(2026, 10, 26)), date(2026, 11, 25))

	def test_eligible_advances_subtracts_claimed_and_scheduled_returns(self):
		rows = [
			frappe._dict(
				name="HR-EAD-1",
				employee="E1",
				employee_name="Budi",
				company="PT A",
				currency="IDR",
				posting_date=date(2026, 9, 21),
				paid_amount=500000,
				claimed_amount=100000,
			),
			frappe._dict(
				name="HR-EAD-2",
				employee="E2",
				employee_name="Sari",
				company="PT A",
				currency="IDR",
				posting_date=date(2026, 9, 21),
				paid_amount=200000,
				claimed_amount=0,
			),
		]
		result = svc.eligible_advances(rows=rows, scheduled={"HR-EAD-1": 150000, "HR-EAD-2": 200000})
		self.assertEqual(len(result), 1)
		self.assertEqual((result[0]["name"], result[0]["remaining_amount"]), ("HR-EAD-1", 250000.0))

	def test_bulk_deduct_requires_permission_and_deduction_component(self):
		with patch("frappe.has_permission", return_value=False):
			self.assertRaises(frappe.PermissionError, svc.get_deduct_targets)
			self.assertRaises(frappe.PermissionError, svc.bulk_deduct_from_salary, ["HR-EAD-1"], "Kasbon", "2026-10-25")

		with (
			patch("frappe.has_permission", return_value=True),
			patch("frappe.db.get_value", return_value=frappe._dict(name="Uang Makan", type="Earning", disabled=0)),
			patch("frappe.throw", side_effect=frappe.ValidationError),
		):
			self.assertRaises(frappe.ValidationError, svc.bulk_deduct_from_salary, ["HR-EAD-1"], "Uang Makan", "2026-10-25")

	def test_bulk_deduct_creates_native_additional_salary_for_remaining_balance(self):
		adv = frappe._dict(
			doctype="Employee Advance",
			name="HR-EAD-1",
			employee="E1",
			employee_name="Budi",
			company="PT A",
			currency="IDR",
			docstatus=1,
			repay_unclaimed_amount_from_salary=1,
			paid_amount=500000,
			claimed_amount=0,
		)
		fake_add = frappe._dict(name="HR-ADS-1")
		events = []
		fake_add.insert = lambda: events.append("insert")
		fake_add.submit = lambda: events.append("submit")

		with (
			patch("frappe.has_permission", return_value=True),
			patch("frappe.db.get_value", return_value=frappe._dict(name="Kasbon", type="Deduction", disabled=0)),
			patch.object(svc, "_scheduled_returns", return_value={"HR-EAD-1": 100000}),
			patch("frappe.db.savepoint"),
			patch("frappe.get_doc", return_value=adv),
			patch.object(svc, "create_return_through_additional_salary", return_value=fake_add) as creator,
			patch.object(svc, "_recalculate_draft_slips", return_value=1) as recalc,
		):
			out = svc.bulk_deduct_from_salary(["HR-EAD-1"], "Kasbon", "2026-10-25")

		creator.assert_called_once_with(adv)
		recalc.assert_called_once_with({"E1"}, date(2026, 10, 25))
		self.assertEqual((fake_add.salary_component, str(fake_add.payroll_date), fake_add.amount), ("Kasbon", "2026-10-25", 400000.0))
		self.assertEqual(events, ["insert", "submit"])
		self.assertEqual(out, {"created": [{"name": "HR-EAD-1", "additional_salary": "HR-ADS-1", "employee_name": "Budi", "amount": 400000.0}], "recalculated": 1, "errors": []})

	def test_recalculate_draft_slips_saves_matching_drafts_only(self):
		saved = []
		slip_doc = frappe._dict()
		slip_doc.save = lambda: saved.append("saved")
		with (
			patch("frappe.get_all", return_value=["SS-1"]) as listing,
			patch("frappe.get_doc", return_value=slip_doc),
		):
			count = svc._recalculate_draft_slips({"E1"}, date(2026, 10, 25))
		self.assertEqual((count, saved), (1, ["saved"]))
		filters = listing.call_args.kwargs["filters"]
		self.assertEqual((filters["docstatus"], filters["start_date"], filters["end_date"]), (0, ["<=", date(2026, 10, 25)], [">=", date(2026, 10, 25)]))

	def test_default_component_resolves_from_history_or_account_mapping_without_hardcoding(self):
		advances = [{"advance_account": "1132.002 - Piutang - PT A"}]
		settings = frappe._dict(component_accounts=[frappe._dict(salary_component="Potongan Advance", account_number="1132.002")])
		with (
			patch("frappe.get_all", return_value=[]),
			patch("frappe.db.get_value", side_effect=lambda dt, name, field, **kw: "1132.002" if dt == "Account" else frappe._dict(name="Potongan Advance", type="Deduction", disabled=0)),
			patch("frappe.get_cached_doc", return_value=settings),
		):
			self.assertEqual(svc._default_deduct_component(advances), "Potongan Advance")

		with patch("frappe.get_all", return_value=["Potongan Lain"]), patch.object(svc, "_active_deduction", return_value="Potongan Lain"):
			self.assertEqual(svc._default_deduct_component(advances), "Potongan Lain")

		with patch("frappe.get_all", return_value=[]):
			self.assertIsNone(svc._default_deduct_component([{}]))
