"""Calendar scope, permissions, workflow and concurrency tests; no business writes."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.api import leave_calendar as api

MODULE = "custom_hr.api.leave_calendar."


def leave(**changes):
	doc = MagicMock()
	values = dict(doctype="Leave Application", name="LEAVE-1", docstatus=0, status="Open", leave_approver="approver@example.com", employee="EMP-1", employee_name="Employee One", from_date="2026-10-30", to_date="2026-11-02", leave_type="Annual Leave", half_day=0, description="Family", company="Company", modified="2026-10-22 10:00:00")
	values.update(changes)
	for field, value in values.items():
		setattr(doc, field, value)
	doc.get.side_effect = lambda field: values.get(field)
	doc.has_permission.return_value = True
	return doc


class TestLeaveCalendar(unittest.TestCase):
	def mock(self, target, **kwargs):
		p = patch(target, **kwargs)
		self.addCleanup(p.stop)
		return p.start()

	def setUp(self):
		self.mock("frappe.session", new=frappe._dict(user="approver@example.com"))
		self.mock("frappe.get_roles", return_value=["Leave Approver"])
		self.mock("frappe.has_permission", return_value=True)
		self.workflow = self.mock(MODULE + "_workflow", return_value=None)
		self.setting = self.mock("frappe.db.get_single_value", return_value=1)
		self.db_read = self.mock("frappe.db.get_value", return_value="employee@example.com")
		# The balance has its own tests below; here it must not add frappe.db.get_value calls.
		self.balance = self.mock(MODULE + "_leave_balance", return_value={"leave_balance": 10.0, "exceeds_balance": False})
		self.doc = leave()
		self.factory = self.mock("frappe.get_doc", return_value=self.doc)
		self.listing = self.mock("frappe.get_list", side_effect=lambda dt, **kwargs: [frappe._dict(name="LEAVE-1")] if dt == "Leave Application" else [])

	def tearDown(self):
		frappe.clear_messages()

	def test_calendar_counts_leave_on_each_overlapping_date_only(self):
		result = api.get_leave_calendar("2026-11-01", "2026-11-30", kind="leave")
		expected = {"leave": 1, "overtime": 0, "leave_request": 1, "approved_leave": 0, "rejected": 0, "cancelled": 0}
		self.assertEqual(result["counts"], {"2026-11-01": expected, "2026-11-02": expected})
		self.assertEqual(len(result["items"]), 1)

	def test_listing_uses_read_permissions_without_approver_or_stage_filter(self):
		api.get_leave_calendar("2026-10-01", "2026-10-31", company="Company", employee="EMP-1", kind="leave")
		args = self.listing.call_args.kwargs
		self.assertNotIn("leave_approver", args["filters"])
		self.assertNotIn("docstatus", args["filters"])
		self.assertNotIn("status", args["filters"])
		self.assertEqual(args["filters"]["company"], "Company")
		self.assertEqual(args["filters"]["employee"], "EMP-1")
		self.assertNotIn("ignore_permissions", args)

	def test_invalid_range_or_type_rejected_before_query(self):
		for start, end in [(None, "2026-10-01"), ("2026-11-01", "2026-10-01"), ("2026-01-01", "2026-12-31")]:
			with self.assertRaises(frappe.ValidationError):
				api.get_leave_calendar(start, end)
		with self.assertRaises(frappe.ValidationError):
			api.get_leave_calendar("2026-10-01", "2026-10-31", kind="salary")
		self.listing.assert_not_called()

	def test_no_read_permission_yields_no_data_or_counts(self):
		with patch("frappe.has_permission", return_value=False):
			self.assertEqual(api.get_leave_calendar("2026-10-01", "2026-10-31")["counts"], {})
		self.listing.assert_not_called()

	def test_readable_non_approver_request_is_visible_but_has_no_actions(self):
		self.doc.leave_approver = "other@example.com"
		self.assertEqual(api._actions(self.doc), [])
		result = api.get_leave_calendar("2026-10-01", "2026-10-31")
		self.assertEqual(len(result["items"]), 1)
		self.assertEqual(result["items"][0]["actions"], [])
		self.assertEqual(result["counts"]["2026-10-30"]["leave"], 1)
		with self.assertRaises(frappe.PermissionError):
			api.decide_approval("Leave Application", "LEAVE-1", "Approve", str(self.doc.modified))
		self.doc.submit.assert_not_called()

	def test_document_without_read_permission_is_not_returned(self):
		self.doc.has_permission.return_value = False
		result = api.get_leave_calendar("2026-10-01", "2026-10-31")
		self.assertEqual(result["items"], [])
		self.assertEqual(result["counts"], {})

	def test_approved_and_rejected_requests_remain_visible_read_only(self):
		for status in ["Approved", "Rejected", "Cancelled"]:
			self.factory.return_value = leave(docstatus=2 if status == "Cancelled" else 1, status=status)
			result = api.get_leave_calendar("2026-10-01", "2026-10-31")
			self.assertEqual(result["items"][0]["status"], status)
			self.assertEqual(result["items"][0]["actions"], [])

	def test_other_workflow_stage_remains_visible_without_actions(self):
		self.workflow.return_value = frappe._dict(workflow_state_field="leave_workflow_state")
		self.factory.return_value = leave(leave_workflow_state="Menunggu PL", leave_approver_name="Budi")
		with patch(MODULE + "get_transitions", return_value=[]):
			result = api.get_leave_calendar("2026-10-01", "2026-10-31")
		self.assertEqual(result["items"][0]["status"], "Waiting for Budi")
		self.assertEqual(result["items"][0]["actions"], [])

	def test_native_self_approval_respects_hr_settings(self):
		self.db_read.return_value = "approver@example.com"
		self.assertEqual([a["action"] for a in api._actions(self.doc)], ["Reject"])
		self.setting.return_value = 0
		self.assertEqual([a["action"] for a in api._actions(self.doc)], ["Approve", "Reject"])

	def test_submit_permission_required_for_native_leave(self):
		self.doc.has_permission.side_effect = lambda permission: permission != "submit"
		self.assertEqual(api._actions(self.doc), [])

	def test_final_or_submitted_requests_have_no_actions(self):
		for docstatus, status in [(1, "Approved"), (2, "Cancelled"), (0, "Rejected")]:
			self.assertEqual(api._actions(leave(docstatus=docstatus, status=status)), [])

	def test_workflow_filters_self_approval_and_preserves_next_stage(self):
		transitions = [frappe._dict(action="Setujui", next_state="Menunggu HRD"), frappe._dict(action="Tolak", next_state="Ditolak")]
		with patch(MODULE + "get_transitions", return_value=transitions), patch(MODULE + "has_approval_access", side_effect=[True, False]):
			actions = api._actions(self.doc, MagicMock())
		self.assertEqual(actions, [{"action": "Setujui", "kind": "approve", "next_state": "Menunggu HRD"}])

	def test_workflow_conditions_are_not_replaced_with_role_only_checks(self):
		with patch(MODULE + "get_transitions", return_value=[]):
			self.assertEqual(api._actions(self.doc, MagicMock()), [])

	def test_no_workflow_overtime_does_not_bypass_approval(self):
		self.assertEqual(api._actions(leave(doctype="Overtime Request")), [])

	def test_query_overflow_fails_instead_of_silently_truncating(self):
		self.listing.side_effect = None
		self.listing.return_value = [frappe._dict(name="LEAVE")] * (api.MAX_REQUESTS + 1)
		with self.assertRaises(frappe.ValidationError):
			api.get_leave_calendar("2026-10-01", "2026-10-31")

	def test_month_counts_match_detail_without_loading_documents_or_workflow(self):
		row = frappe._dict(from_date=self.doc.from_date, to_date=self.doc.to_date, status="Open", docstatus=0)
		self.listing.side_effect = lambda dt, **kwargs: [row] if dt == "Leave Application" else []
		detail = api.get_leave_calendar("2026-11-01", "2026-11-30", kind="leave")["counts"]
		self.factory.reset_mock()
		self.workflow.reset_mock()
		result = api.get_leave_counts("2026-11-01", "2026-11-30", company="Company", employee="EMP-1")
		self.assertEqual(result["counts"], detail)
		self.assertEqual(result["total"], 1)
		self.factory.assert_not_called()
		self.workflow.assert_not_called()
		args = [call.kwargs for call in self.listing.call_args_list if call.args[0] == "Leave Application"][-1]  # the month count, not the detail
		self.assertEqual(args["limit_page_length"], 0)
		self.assertEqual(args["filters"]["company"], "Company")
		self.assertEqual(args["filters"]["employee"], "EMP-1")
		self.assertNotIn("ignore_permissions", args)

	def test_month_counts_do_not_cap_or_fail_on_large_volume(self):
		row = frappe._dict(from_date="2026-11-03", to_date="2026-11-03", status="Approved", docstatus=1)
		self.listing.side_effect = lambda dt, **kwargs: [row] * (api.MAX_REQUESTS + 100) if dt == "Leave Application" else []
		result = api.get_leave_counts("2026-11-01", "2026-11-30")
		self.assertEqual(result["total"], api.MAX_REQUESTS + 100)
		self.assertEqual(result["counts"]["2026-11-03"]["approved_leave"], api.MAX_REQUESTS + 100)

	def test_month_counts_respect_read_permission_and_range(self):
		with patch("frappe.has_permission", return_value=False):
			self.assertEqual(api.get_leave_counts("2026-11-01", "2026-11-30")["counts"], {})
		self.listing.assert_not_called()
		with self.assertRaises(frappe.ValidationError):
			api.get_leave_counts("2026-01-01", "2026-12-31")

	def test_decision_rechecks_modified_and_does_not_mutate_stale_document(self):
		with self.assertRaisesRegex(frappe.ValidationError, "has changed"):
			api.decide_approval("Leave Application", "LEAVE-1", "Approve", "OLD")
		self.doc.submit.assert_not_called()
		self.db_read.assert_called_with("Leave Application", "LEAVE-1", "name", for_update=True)
		self.doc.reload.assert_called_once()

	def test_native_approve_submits_with_real_lifecycle_without_permission_bypass(self):
		result = api.decide_approval("Leave Application", "LEAVE-1", "Approve", str(self.doc.modified))
		self.assertEqual(result["status"], "Approved")
		self.doc.submit.assert_called_once_with()
		self.doc.save.assert_not_called()

	def test_native_reject_submits_rejected_status(self):
		result = api.decide_approval("Leave Application", "LEAVE-1", "Reject", str(self.doc.modified))
		self.assertEqual(result["status"], "Rejected")
		self.doc.submit.assert_called_once_with()

	def test_unauthorized_or_forged_action_never_mutates_document(self):
		for action in ["Delete", "Setujui (HRD)"]:
			with self.assertRaises(frappe.PermissionError):
				api.decide_approval("Leave Application", "LEAVE-1", action, str(self.doc.modified))
		self.doc.submit.assert_not_called()

	def test_unrelated_doctype_rejected_before_loading(self):
		with self.assertRaises(frappe.ValidationError):
			api.decide_approval("Salary Slip", "SLIP", "Approve", "DATE")
		self.factory.assert_not_called()

	def test_overtime_decision_is_bound_to_one_employee(self):
		workflow = frappe._dict(workflow_state_field="status")
		self.workflow.return_value = workflow
		allowed = [{"action": "Setujui", "kind": "approve", "next_state": "Menunggu SPV"}]
		self.doc.get.side_effect = None
		self.doc.get.return_value = "Menunggu SPV"
		self.doc.employees = [frappe._dict(employee="EMP-1", approval_state="Menunggu Leader")]
		with patch(MODULE + "_actions", return_value=allowed), patch(MODULE + "decide_employee", return_value={"status": "Menunggu SPV"}) as decide:
			result = api.decide_approval("Overtime Request", "OT-1", "Setujui", str(self.doc.modified), employee="EMP-1")
		decide.assert_called_once_with(self.doc, "EMP-1", "Setujui", workflow)
		self.assertEqual(result["status"], "Menunggu SPV")
		self.doc.submit.assert_not_called()

	def test_overtime_displays_one_employee_per_item_and_uses_work_date(self):
		doc = leave(doctype="Overtime Request", date="2026-10-22", start_time="17:00:00", end_time="19:00:00", planned_hours=2, employees=[frappe._dict(employee="EMP-A", employee_name="A"), frappe._dict(employee="EMP-B", employee_name="B")])
		item = api._request(doc, "overtime", [], None, doc.employees[0])
		self.assertEqual(len(item["employees"]), 1)
		self.assertEqual(item["employee"], "EMP-A")
		self.assertEqual(item["from_date"], "2026-10-22")
		self.assertEqual(item["to_date"], "2026-10-22")

	def test_overtime_cannot_be_decided_without_employee_identity(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Choose the employee"):
			api.decide_approval("Overtime Request", "OT-1", "Setujui", str(self.doc.modified))
		self.doc.submit.assert_not_called()

	def test_grouped_overtime_becomes_individual_calendar_rows_and_employee_filter(self):
		doc = leave(doctype="Overtime Request", date="2026-10-22", start_time="19:00:00", end_time="21:00:00", planned_hours=2, employees=[frappe._dict(employee="EMP-A", employee_name="A", approval_state="Menunggu HRD"), frappe._dict(employee="EMP-B", employee_name="B", approval_state="Menunggu HRD")])
		self.factory.return_value = doc
		self.listing.side_effect = lambda dt, **kwargs: [frappe._dict(name="OT")] if dt == "Overtime Request" else []
		with patch(MODULE + "_actions", return_value=[{"action": "Setujui", "kind": "approve", "next_state": "Disetujui"}]):
			result = api.get_leave_calendar("2026-10-22", "2026-10-22", kind="overtime")
			filtered = api.get_leave_calendar("2026-10-22", "2026-10-22", employee="EMP-B", kind="overtime")
		self.assertEqual([i["employee"] for i in result["items"]], ["EMP-A", "EMP-B"])
		self.assertEqual(result["counts"]["2026-10-22"]["overtime"], 2)
		self.assertEqual([i["employee"] for i in filtered["items"]], ["EMP-B"])

	def test_moved_request_no_longer_in_range_is_not_returned(self):
		self.doc.from_date = "2027-01-01"
		self.doc.to_date = "2027-01-02"
		self.assertEqual(api.get_leave_calendar("2026-10-01", "2026-10-31")["items"], [])

	def test_default_calendar_lists_leave_and_overtime(self):
		api.get_leave_calendar("2026-10-01", "2026-10-31")
		self.assertEqual([call.args[0] for call in self.listing.call_args_list], ["Leave Application", "Overtime Request"])
		api.get_leave_calendar("2026-10-01", "2026-10-31", kind="overtime")
		self.assertEqual(self.listing.call_args.args[0], "Overtime Request")

	def test_pending_overtime_is_listed_view_only_for_a_non_approver_and_decided_employees_drop_out(self):
		doc = leave(doctype="Overtime Request", date="2026-10-22", start_time="17:00:00", end_time="19:00:00", planned_hours=2, status="Menunggu SPV", employees=[frappe._dict(employee="EMP-A", employee_name="A"), frappe._dict(employee="EMP-B", employee_name="B", approval_state="Ditolak")])
		self.factory.return_value = doc
		self.listing.side_effect = lambda dt, **kwargs: [frappe._dict(name="OT")] if dt == "Overtime Request" else []
		with patch(MODULE + "_actions", return_value=[]):
			result = api.get_leave_calendar("2026-10-22", "2026-10-22", kind="overtime")
		self.assertEqual([(i["employee"], i["status"], i["actions"]) for i in result["items"]], [("EMP-A", "Menunggu SPV", [])])

	def test_overtime_status_names_the_leader_or_spv_like_leave(self):
		approvers = {"approver_1": "leader@example.com", "approver_2": "spv@example.com"}
		names = {"leader@example.com": "Budi", "spv@example.com": "Sari"}
		for status, expected in [("Menunggu Leader", "Waiting for Budi"), ("Menunggu SPV", "Waiting for Sari"), ("Menunggu HRD", "Menunggu HRD")]:
			doc = leave(doctype="Overtime Request", date="2026-10-22", start_time="17:00:00", end_time="19:00:00", planned_hours=2, status=status, **approvers, employees=[frappe._dict(employee="EMP-A", employee_name="A")])
			with self.subTest(status=status), patch("frappe.db.get_value", side_effect=lambda doctype, name, field: names[name]):
				self.assertEqual(api._request(doc, "overtime", [], None, doc.employees[0])["status"], expected)

	def test_month_counts_include_each_pending_overtime_employee(self):
		requests = [frappe._dict(name="OT-1", date="2026-10-22", status="Menunggu Leader"), frappe._dict(name="OT-2", date="2026-10-23", status="Menunggu HRD")]
		members = [
			frappe._dict(parent="OT-1", employee="EMP-A", approval_state=None),
			frappe._dict(parent="OT-1", employee="EMP-B", approval_state="Disetujui"),
			frappe._dict(parent="OT-2", employee="EMP-A", approval_state=None),
		]
		self.listing.side_effect = lambda dt, **kwargs: requests if dt == "Overtime Request" else []
		with patch("frappe.get_all", return_value=members) as rows:
			result = api.get_leave_counts("2026-10-01", "2026-10-31", company="Company")
			filtered = api.get_leave_counts("2026-10-01", "2026-10-31", employee="EMP-B")
		self.assertEqual((result["counts"]["2026-10-22"]["overtime"], result["counts"]["2026-10-23"]["overtime"], result["total"]), (1, 1, 2))
		self.assertEqual(filtered["total"], 0)
		listing = next(call.kwargs for call in self.listing.call_args_list if call.args[0] == "Overtime Request")
		self.assertEqual(listing["filters"]["company"], "Company")
		self.assertNotIn("ignore_permissions", listing)
		self.assertEqual(rows.call_args.kwargs["filters"]["parent"], ["in", ["OT-1", "OT-2"]])

	def test_leave_classification_requires_native_final_submission(self):
		for status, docstatus, expected in [
			("Open", 0, "leave_request"),
			("Approved", 0, "leave_request"),
			("Approved", 1, "approved_leave"),
			("Rejected", 1, "rejected"),
			("Approved", 2, "cancelled"),
			("Cancelled", 2, "cancelled"),
		]:
			with self.subTest(status=status, docstatus=docstatus):
				self.assertEqual(api._leave_calendar_status(leave(status=status, docstatus=docstatus)), expected)

	def test_outlet_comes_from_native_employee_not_retired_custom_routing(self):
		self.db_read.return_value = "Native Outlet"
		doc = leave(outlet_leave_outlet="Retired Outlet")
		result = api._request(doc, "leave", [], None)
		self.assertEqual(result["outlet"], "Native Outlet")
		self.db_read.assert_called_once_with("Employee", doc.employee, "outlet")

	def test_pending_and_approved_counts_are_separate_for_same_date(self):
		docs = {
			"PENDING": leave(name="PENDING"),
			"APPROVED": leave(name="APPROVED", status="Approved", docstatus=1),
			"REJECTED": leave(name="REJECTED", status="Rejected", docstatus=1),
			"CANCELLED": leave(name="CANCELLED", status="Cancelled", docstatus=2),
		}
		self.factory.side_effect = lambda dt, name: docs[name]
		self.listing.side_effect = lambda dt, **kw: [frappe._dict(name=name) for name in docs] if dt == "Leave Application" else []
		result = api.get_leave_calendar("2026-10-30", "2026-10-30")
		self.assertEqual(len(result["items"]), 4)
		self.assertEqual(result["counts"]["2026-10-30"], {
			"leave": 4, "overtime": 0, "leave_request": 1, "approved_leave": 1, "rejected": 1, "cancelled": 1,
		})

	def test_leave_items_carry_the_remaining_balance_for_the_approver(self):
		item = api.get_leave_calendar("2026-10-30", "2026-10-30")["items"][0]
		self.assertEqual((item["leave_balance"], item["exceeds_balance"]), (10.0, False))
		self.balance.assert_called_once_with(self.doc)

	def test_the_full_reason_is_sent_not_a_shortened_copy(self):
		self.doc.description = "Menghadiri pernikahan saudara di luar kota selama beberapa hari, " * 3
		item = api.get_leave_calendar("2026-10-30", "2026-10-30")["items"][0]
		self.assertEqual(item["description"], self.doc.description)


class TestLeaveBalance(unittest.TestCase):
	def setUp(self):
		self.rules = frappe._dict(is_lwp=0, allow_negative=0)
		self.remaining = 5.0
		self.get_value = patch("frappe.db.get_value", side_effect=lambda *a, **k: self.rules)
		self.balance_on = patch(MODULE + "get_leave_balance_on", side_effect=lambda *a, **k: self.remaining)
		self.get_value.start()
		self.balance = self.balance_on.start()
		self.addCleanup(self.get_value.stop)
		self.addCleanup(self.balance_on.stop)
		self.doc = leave(total_leave_days=3)

	def test_balance_is_read_on_the_first_day_with_access_via_the_application(self):
		self.assertEqual(api._leave_balance(self.doc), {"leave_balance": 5.0, "exceeds_balance": False})
		args, kwargs = self.balance.call_args
		self.assertEqual(args[:2], ("EMP-1", "Annual Leave"))
		self.assertEqual(str(args[2]), "2026-10-30")
		self.assertEqual(kwargs["leave_application"], "LEAVE-1")

	def test_a_request_larger_than_the_balance_is_flagged(self):
		self.remaining = 2.0
		self.assertEqual(api._leave_balance(self.doc), {"leave_balance": 2.0, "exceeds_balance": True})

	def test_a_request_equal_to_the_balance_is_not_flagged(self):
		self.remaining = 3.0
		self.assertFalse(api._leave_balance(self.doc)["exceeds_balance"])

	def test_a_leave_type_that_allows_negative_balance_is_never_flagged(self):
		self.rules.allow_negative = 1
		self.remaining = 0.0
		self.assertFalse(api._leave_balance(self.doc)["exceeds_balance"])

	def test_leave_without_pay_has_no_balance_to_show(self):
		self.rules.is_lwp = 1
		self.assertEqual(api._leave_balance(self.doc), {"leave_balance": None, "exceeds_balance": False})
		self.balance.assert_not_called()

	def test_an_unknown_leave_type_is_treated_as_a_normal_one(self):
		self.rules = None
		self.assertEqual(api._leave_balance(self.doc)["leave_balance"], 5.0)
