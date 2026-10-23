"""Employee decisions cannot promote/reject another member or bypass workflow."""

import unittest
from copy import deepcopy
from unittest.mock import patch

import frappe

from custom_hr.services import overtime_approval as service
from custom_hr.api import overtime_pay


def request():
	return frappe.get_doc({
		"doctype": "Overtime Request", "name": "OT-TEST", "owner": "requester@example.com",
		"status": "Menunggu Leader", "company": "Company", "date": "2026-10-28",
		"start_time": "17:00:00", "end_time": "19:00:00", "overtime_type": "Lembur",
		"employees": [{"name": "ROW-A", "employee": "EMP-A", "employee_name": "A"}, {"name": "ROW-B", "employee": "EMP-B", "employee_name": "B"}],
	})


class TestEmployeeOvertimeApproval(unittest.TestCase):
	def setUp(self):
		self.doc = request()
		self.workflow = frappe._dict(workflow_state_field="status", states=[frappe._dict(state=s, doc_status="0", update_field=None) for s in [*service.PENDING_STATES, *service.FINAL_STATES]])

	def tearDown(self):
		frappe.clear_messages()

	def transition(self, state):
		return frappe._dict(action="Setujui", next_state=state, transition_tasks=None)

	def decide(self, employee, next_state, access=True):
		with patch.object(service, "get_transitions", return_value=[self.transition(next_state)]), patch.object(service, "has_approval_access", return_value=access), patch.object(self.doc, "save") as save, patch.object(self.doc, "add_comment"):
			result = service.decide_employee(self.doc, employee, "Setujui", self.workflow)
		return result, save

	def test_approve_only_one_employee_and_keep_other_at_original_stage(self):
		result, save = self.decide("EMP-A", "Menunggu SPV")
		self.assertEqual(self.doc.employees[0].approval_state, "Menunggu SPV")
		self.assertEqual(self.doc.employees[1].approval_state, "Menunggu Leader")
		self.assertFalse(self.doc.employees[1].decision_by)
		self.assertEqual(result["request_status"], "Menunggu Leader")
		save.assert_called_once_with()
		self.assertNotIn("employee_decision_token", self.doc.flags)

	def test_mixed_final_decisions_preserved_and_parent_is_only_summary(self):
		self.doc.employees[0].approval_state = "Disetujui"
		self.doc.employees[1].approval_state = "Menunggu HRD"
		result, _ = self.decide("EMP-B", "Ditolak")
		self.assertEqual(result["request_status"], "Disetujui")
		self.assertEqual(self.doc.employees[0].approval_state, "Disetujui")
		self.assertEqual(self.doc.employees[1].approval_state, "Ditolak")

	def test_earliest_pending_stage_determines_parent_summary(self):
		self.doc.employees[0].approval_state = "Menunggu HRD"
		self.doc.employees[1].approval_state = "Menunggu SPV"
		self.assertEqual(service.aggregate_state(self.doc), "Menunggu SPV")

	def test_all_rejected_means_parent_rejected(self):
		for row in self.doc.employees:
			row.approval_state = "Ditolak"
		self.assertEqual(service.aggregate_state(self.doc), "Ditolak")

	def test_foreign_employee_or_final_employee_is_rejected(self):
		with self.assertRaises(frappe.PermissionError):
			service.decide_employee(self.doc, "FOREIGN", "Setujui", self.workflow)
		self.doc.employees[0].approval_state = "Ditolak"
		with self.assertRaises(frappe.ValidationError):
			service.decide_employee(self.doc, "EMP-A", "Setujui", self.workflow)

	def test_workflow_self_approval_condition_cannot_be_bypassed(self):
		with self.assertRaises(frappe.PermissionError):
			self.decide("EMP-A", "Disetujui", access=False)
		self.assertFalse(self.doc.employees[0].approval_state)

	def test_assignment_stamping_only_targets_approved_employee(self):
		self.doc.status = "Disetujui"
		self.doc.employees[0].approval_state = "Disetujui"
		self.doc.employees[1].approval_state = "Ditolak"
		with patch("frappe.get_all", return_value=[] ) as query:
			self.doc.stamp_assignments()
		self.assertEqual(query.call_count, 1)
		self.assertEqual(query.call_args.kwargs["filters"]["employee"], "EMP-A")

	def test_external_raw_document_cannot_edit_row_decision(self):
		old = deepcopy(self.doc)
		self.doc.employees[0].approval_state = "Disetujui"
		self.doc.flags.employee_decision_token = True  # Client boolean is not the token.
		with patch.object(self.doc, "get_doc_before_save", return_value=old), self.assertRaises(frappe.PermissionError):
			service.protect_employee_decisions(self.doc)

	def test_external_group_workflow_cannot_decide_multiple_employees(self):
		old = deepcopy(self.doc)
		self.doc.status = "Disetujui"
		with patch.object(self.doc, "get_doc_before_save", return_value=old), self.assertRaises(frappe.ValidationError):
			service.protect_employee_decisions(self.doc)

	def test_approved_row_cannot_be_removed_from_request(self):
		self.doc.employees[0].approval_state = "Disetujui"
		old = deepcopy(self.doc)
		self.doc.employees = [self.doc.employees[1]]
		with patch.object(self.doc, "get_doc_before_save", return_value=old), self.assertRaises(frappe.ValidationError):
			service.protect_employee_decisions(self.doc)

	def test_legacy_rows_keep_parent_state_until_first_individual_action(self):
		self.doc.status = "Menunggu HRD"
		self.assertEqual(service.employee_state(self.doc, self.doc.employees[0]), "Menunggu HRD")
		self.assertEqual(service.employee_view(self.doc, self.doc.employees[0]).status, "Menunggu HRD")

	def test_payroll_only_includes_approved_employee_even_when_parent_is_pending(self):
		settings = frappe._dict(overtime_hourly_divisor=173, overtime_salary_component="Lembur")
		requests = [frappe._dict(name="OT", date="2026-10-28", planned_hours=2, status="Menunggu HRD")]
		rows = [frappe._dict(parent="OT", employee="EMP-A", approval_state="Disetujui"), frappe._dict(parent="OT", employee="EMP-B", approval_state="Ditolak"), frappe._dict(parent="OT", employee="EMP-C", approval_state="Menunggu HRD")]
		attendance = [frappe._dict(employee="EMP-A", attendance_date="2026-10-28", actual_overtime_duration=2)]
		def query(doctype, **kwargs):
			return {"Overtime Request": requests, "Overtime Request Employee": rows, "Attendance": attendance}[doctype]
		with patch("frappe.get_cached_doc", return_value=settings), patch("frappe.get_all", side_effect=query), patch.object(overtime_pay, "_wage_base", return_value=1730000), patch("frappe.db.get_value", return_value=frappe._dict(employee_name="A", department="Office")):
			result = overtime_pay.collect_month("2026-10-01")
		self.assertEqual([r["employee"] for r in result["rows"]], ["EMP-A"])
		self.assertEqual(result["rows"][0]["amount"], 35000)

	def test_new_document_cannot_supply_preapproved_employee(self):
		doc = frappe.get_doc({"doctype": "Overtime Request", "employees": [{"employee": "EMP-A", "approval_state": "Disetujui"}]})
		with self.assertRaises(frappe.PermissionError):
			service.protect_employee_decisions(doc)

	def test_rejected_employee_can_be_re_requested_without_blocking_other_members(self):
		self.doc.employees[0].approval_state = "Ditolak"
		with patch("frappe.get_all", side_effect=[[frappe._dict(name="OTHER")], []]) as query:
			self.doc.validate_no_duplicate()
		self.assertEqual(query.call_args.kwargs["filters"]["employee"], ["in", ["EMP-B"]])
