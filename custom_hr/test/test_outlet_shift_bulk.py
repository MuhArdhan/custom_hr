"""Bulk attach/detach of one Shift Type across Outlets: diff based, per-outlet failure isolation."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.api import outlet as api

MODULE = "custom_hr.api.outlet."


def outlet(name, shifts=()):
	doc = MagicMock()
	doc.name = name
	doc.shifts = [frappe._dict(shift_type=shift) for shift in shifts]
	doc.append.side_effect = lambda field, row: doc.shifts.append(frappe._dict(row))
	doc.remove.side_effect = lambda row: doc.shifts.remove(row)
	return doc


class TestOutletShiftBulk(unittest.TestCase):
	def mock(self, target, **kwargs):
		p = patch(target, **kwargs)
		self.addCleanup(p.stop)
		return p.start()

	def setUp(self):
		self.only_for = self.mock("frappe.only_for")
		self.exists = self.mock("frappe.db.exists", return_value=True)
		self.docs = {}
		self.mock("frappe.get_doc", side_effect=lambda doctype, name: self.docs[name])
		self.mock("frappe.db.savepoint")
		self.rollback = self.mock("frappe.db.rollback")
		self.commit = self.mock("frappe.db.commit")
		self.mock("frappe.clear_messages")

	def tearDown(self):
		frappe.clear_messages()

	def names(self, name):
		return [row.shift_type for row in self.docs[name].shifts]

	def test_adds_an_enabled_row_and_removes_only_the_requested_shift(self):
		self.docs = {"A": outlet("A"), "B": outlet("B", ["Pagi", "Siang"])}
		result = api.set_shift_outlets("Pagi", add='["A"]', remove='["B"]')
		self.assertEqual(result, {"added": 1, "removed": 1, "unchanged": 0, "failed": []})
		self.docs["A"].append.assert_called_once_with("shifts", {"shift_type": "Pagi", "enabled": 1})
		self.assertEqual(self.names("A"), ["Pagi"])
		self.assertEqual(self.names("B"), ["Siang"])
		self.docs["A"].save.assert_called_once()
		self.docs["B"].save.assert_called_once()
		self.commit.assert_called_once()

	def test_a_stale_diff_changes_nothing_and_is_counted_as_unchanged(self):
		self.docs = {"A": outlet("A", ["Pagi"]), "B": outlet("B")}
		result = api.set_shift_outlets("Pagi", add=["A"], remove=["B"])
		self.assertEqual(result, {"added": 0, "removed": 0, "unchanged": 2, "failed": []})
		for name in self.docs:
			self.docs[name].save.assert_not_called()

	def test_one_invalid_outlet_is_reported_and_rolled_back_without_stopping_the_rest(self):
		self.docs = {"A": outlet("A"), "B": outlet("B", ["Pagi"]), "C": outlet("C")}
		self.docs["B"].save.side_effect = frappe.ValidationError("Mode shift otomatis membutuhkan minimal satu shift aktif.")
		result = api.set_shift_outlets("Pagi", add=["A", "C"], remove=["B"])
		self.assertEqual((result["added"], result["removed"]), (2, 0))
		self.assertEqual([row["outlet"] for row in result["failed"]], ["B"])
		self.assertIn("minimal satu shift aktif", result["failed"][0]["error"])
		self.docs["C"].save.assert_called_once()
		self.rollback.assert_called_once()

	def test_only_hr_roles_may_run_it_and_nothing_is_loaded_otherwise(self):
		self.only_for.side_effect = frappe.PermissionError
		with self.assertRaises(frappe.PermissionError):
			api.set_shift_outlets("Pagi", add=["A"])
		self.only_for.assert_called_with(api.OUTLET_ROLES)
		self.assertEqual(self.docs, {})

	def test_unknown_shift_type_is_rejected_before_any_outlet_is_touched(self):
		self.docs = {"A": outlet("A")}
		self.exists.return_value = False
		with self.assertRaises(frappe.ValidationError):
			api.set_shift_outlets("Hantu", add=["A"])
		self.docs["A"].save.assert_not_called()
		self.commit.assert_not_called()

	def test_an_outlet_in_both_lists_is_rejected(self):
		self.docs = {"A": outlet("A")}
		with self.assertRaises(frappe.ValidationError):
			api.set_shift_outlets("Pagi", add=["A"], remove=["A"])
		self.docs["A"].save.assert_not_called()

	def test_repeated_outlet_names_are_handled_once(self):
		self.docs = {"A": outlet("A")}
		result = api.set_shift_outlets("Pagi", add=["A", "A"])
		self.assertEqual(result["added"], 1)
		self.docs["A"].save.assert_called_once()

	def test_lists_every_active_outlet_flagging_those_that_have_the_shift(self):
		self.mock(MODULE + "frappe.get_all", side_effect=lambda doctype, **kwargs: {
			"Outlet": ["A", "B", "C"],
			"Outlet Shift": ["B"],
		}[doctype])
		self.assertEqual(api.get_shift_outlets("Pagi"), [
			{"outlet": "A", "has_shift": False},
			{"outlet": "B", "has_shift": True},
			{"outlet": "C", "has_shift": False},
		])
		self.only_for.assert_called_with(api.OUTLET_ROLES)
