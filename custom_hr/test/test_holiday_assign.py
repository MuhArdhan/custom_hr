"""Bulk Holiday List Assignment tool: add-only, per-target failure isolation."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.api import holiday as api


class TestHolidayAssign(unittest.TestCase):
	def mock(self, target, **kwargs):
		p = patch(target, **kwargs)
		self.addCleanup(p.stop)
		return p.start()

	def setUp(self):
		self.only_for = self.mock("frappe.only_for")
		self.lists = {"Libur Minggu", "Tanpa Libur"}
		self.mock("frappe.db.exists", side_effect=lambda doctype, name=None: name in self.lists if doctype == "Holiday List" else True)
		self.companies = ["A", "B", "C"]
		self.employees = [frappe._dict(name="E1", employee_name="Siti"), frappe._dict(name="E2", employee_name="Budi")]
		# submitted assignments: (assigned_to, holiday_list, from_date)
		self.assignments = []
		self.created = []
		self.fail_for = set()

		def get_all(doctype, filters=None, **kwargs):
			filters = filters or {}
			if doctype == "Company":
				return list(self.companies)
			if doctype == "Employee":
				return list(self.employees)
			if doctype == "Holiday List Assignment":
				rows = [
					frappe._dict(assigned_to=a, holiday_list=h, from_date=d)
					for a, h, d in self.assignments if filters.get("applicable_for") == self.kind
				]
				if "assigned_to" in filters:
					rows = [r for r in rows if r.assigned_to == filters["assigned_to"]]
				if "from_date" in filters:
					rows = [r for r in rows if str(r.from_date) <= str(filters["from_date"][1])]
				return sorted(rows, key=lambda r: str(r.from_date), reverse=kwargs.get("order_by") == "from_date desc")
			return []

		def get_doc(values):
			doc = MagicMock()
			doc.name = f"HLA-{len(self.created)}"
			if values["assigned_to"] in self.fail_for:
				doc.insert.side_effect = frappe.ValidationError("Penugasan bertabrakan")
			doc.insert.return_value = doc
			self.created.append(values)
			return doc

		self.kind = "Company"
		self.mock("frappe.get_all", side_effect=get_all)
		self.mock("frappe.get_doc", side_effect=get_doc)
		self.mock("frappe.db.savepoint")
		self.rollback = self.mock("frappe.db.rollback")
		self.commit = self.mock("frappe.db.commit")
		self.mock("frappe.clear_messages")

	def tearDown(self):
		frappe.clear_messages()

	# --- listing -------------------------------------------------------------------------
	def test_lists_every_company_with_the_list_it_currently_uses(self):
		self.assignments = [("A", "Libur Minggu", "2026-01-01"), ("B", "Tanpa Libur", "2020-01-01"), ("B", "Libur Minggu", "2026-06-01")]
		with patch(api.__name__ + ".getdate", return_value=frappe.utils.getdate("2026-10-24")):
			rows = api.get_holiday_targets("Libur Minggu", "Company")
		by_name = {row["name"]: row for row in rows}
		self.assertEqual(list(by_name), ["A", "B", "C"])
		self.assertEqual((by_name["A"]["holiday_list"], by_name["A"]["on_list"]), ("Libur Minggu", True))
		self.assertEqual((by_name["B"]["holiday_list"], by_name["B"]["on_list"]), ("Libur Minggu", True))  # the newer one wins
		self.assertEqual((by_name["C"]["holiday_list"], by_name["C"]["on_list"]), (None, False))

	def test_an_assignment_that_starts_in_the_future_is_not_the_current_list(self):
		self.assignments = [("A", "Libur Minggu", "2027-01-01")]
		with patch(api.__name__ + ".getdate", return_value=frappe.utils.getdate("2026-10-24")):
			(row,) = [r for r in api.get_holiday_targets("Libur Minggu", "Company") if r["name"] == "A"]
		self.assertEqual((row["holiday_list"], row["on_list"]), (None, False))

	def test_employees_are_listed_by_name_and_id(self):
		self.kind = "Employee"
		rows = api.get_holiday_targets("Libur Minggu", "Employee")
		self.assertEqual([row["label"] for row in rows], ["Siti (E1)", "Budi (E2)"])

	# --- assigning -----------------------------------------------------------------------
	def test_creates_and_submits_one_assignment_per_target(self):
		result = api.assign_holiday_list("Libur Minggu", "Company", '["A", "B"]', "2026-01-01")
		self.assertEqual(result, {"assigned": 2, "unchanged": 0, "failed": []})
		self.assertEqual(
			self.created,
			[
				{"doctype": "Holiday List Assignment", "applicable_for": "Company", "assigned_to": name,
				"holiday_list": "Libur Minggu", "from_date": "2026-01-01"}
				for name in ("A", "B")
			],
		)
		self.commit.assert_called_once()

	def test_a_target_already_on_that_list_is_left_alone(self):
		self.assignments = [("A", "Libur Minggu", "2025-01-01")]
		result = api.assign_holiday_list("Libur Minggu", "Company", ["A", "B"], "2026-01-01")
		self.assertEqual((result["assigned"], result["unchanged"]), (1, 1))
		self.assertEqual([values["assigned_to"] for values in self.created], ["B"])

	def test_switching_from_another_list_adds_a_newer_assignment(self):
		self.assignments = [("A", "Tanpa Libur", "2020-01-01")]
		result = api.assign_holiday_list("Libur Minggu", "Company", ["A"], "2026-01-01")
		self.assertEqual((result["assigned"], result["unchanged"]), (1, 0))

	def test_one_failing_target_is_rolled_back_and_reported_without_stopping_the_rest(self):
		self.fail_for = {"B"}
		result = api.assign_holiday_list("Libur Minggu", "Company", ["A", "B", "C"], "2026-01-01")
		self.assertEqual(result["assigned"], 2)
		self.assertEqual([row["target"] for row in result["failed"]], ["B"])
		self.assertIn("bertabrakan", result["failed"][0]["error"])
		self.rollback.assert_called_once()

	def test_repeated_targets_are_handled_once(self):
		result = api.assign_holiday_list("Libur Minggu", "Company", ["A", "A"], "2026-01-01")
		self.assertEqual(result["assigned"], 1)

	def test_only_hr_roles_may_use_it(self):
		self.only_for.side_effect = frappe.PermissionError
		for call in (
			lambda: api.get_holiday_targets("Libur Minggu", "Company"),
			lambda: api.assign_holiday_list("Libur Minggu", "Company", ["A"], "2026-01-01"),
		):
			with self.assertRaises(frappe.PermissionError):
				call()
		self.assertEqual(self.created, [])

	def test_unknown_list_target_kind_or_missing_date_is_rejected_before_anything_is_created(self):
		for args in [
			("Tidak Ada", "Company", ["A"], "2026-01-01"),
			("Libur Minggu", "Outlet", ["A"], "2026-01-01"),
			("Libur Minggu", "Company", ["A"], ""),
		]:
			with self.assertRaises(frappe.ValidationError):
				api.assign_holiday_list(*args)
		self.assertEqual(self.created, [])
		self.commit.assert_not_called()
