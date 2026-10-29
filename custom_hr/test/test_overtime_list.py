"""Overtime List: an approved employee gets exactly one read-only row; it follows the request."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.api import overtime as overtime_permissions


def request(*rows, status="Menunggu HRD"):
	doc = frappe.new_doc("Overtime Request")
	doc.update({"name": "OT-1", "status": status, "company": "ROPI", "outlet": "ROPI", "date": "2026-10-29", "overtime_type": "Lembur",
		"start_time": "17:00:00", "end_time": "20:00:00", "planned_hours": 3, "reason": "stok opname"})
	for employee, state in rows:
		doc.append("employees", {"employee": employee, "employee_name": employee, "approval_state": state, "shift": "Pagi"})
	return doc


class TestOvertimeList(unittest.TestCase):
	def sync(self, doc, listed=()):
		created = MagicMock()
		with patch("frappe.get_all", return_value=[frappe._dict(name=f"OTL-{e}", employee=e) for e in listed]), \
			patch("frappe.get_doc", return_value=created) as make, patch("frappe.delete_doc") as remove:
			doc.sync_overtime_list()
		return make, created, remove

	def test_each_approved_employee_gets_one_row_with_the_request_details(self):
		make, created, remove = self.sync(request(("EMP-A", "Disetujui"), ("EMP-B", "Menunggu HRD"), ("EMP-C", "Ditolak")))
		self.assertEqual(make.call_count, 1)
		values = make.call_args.args[0]
		self.assertEqual((values["doctype"], values["employee"], values["overtime_request"], values["planned_hours"], values["shift"]), ("Overtime List", "EMP-A", "OT-1", 3, "Pagi"))
		created.insert.assert_called_once_with(ignore_permissions=True)
		remove.assert_not_called()

	def test_an_approval_of_the_whole_request_lists_every_employee_once(self):
		make, _, _ = self.sync(request(("EMP-A", None), ("EMP-B", None), status="Disetujui"), listed=["EMP-A"])
		self.assertEqual([call.args[0]["employee"] for call in make.call_args_list], ["EMP-B"])  # EMP-A is already listed

	def test_a_listed_employee_that_is_no_longer_approved_is_removed(self):
		make, _, remove = self.sync(request(("EMP-A", "Ditolak")), listed=["EMP-A"])
		make.assert_not_called()
		remove.assert_called_once_with("Overtime List", "OTL-EMP-A", ignore_permissions=True, force=True)

	def test_deleting_the_request_deletes_its_rows(self):
		with patch("frappe.db.delete") as delete:
			request().on_trash()
		delete.assert_called_once_with("Overtime List", {"overtime_request": "OT-1"})

	def test_leaders_see_only_rows_of_their_outlets(self):
		with patch.object(overtime_permissions, "_sees_all", return_value=False), patch.object(overtime_permissions, "_their_outlets", return_value=["OUT-1"]):
			self.assertEqual(overtime_permissions.get_list_permission_query_conditions("leader@example.com"), "`tabOvertime List`.`outlet` in ('OUT-1')")
			self.assertEqual(overtime_permissions.get_permission_query_conditions("leader@example.com"), "`tabOvertime Request`.`outlet` in ('OUT-1')")
