"""Submission routing of the native leave Workflow; conditions are evaluated, nothing is written."""

import unittest
from unittest.mock import patch

import frappe
from frappe.model.workflow import get_workflow_safe_globals
from frappe.utils.safe_exec import safe_eval

from custom_hr.patches.setup_native_leave_workflow import configuration

REQUESTER = "requester@example.com"


def evaluate(rows, *, outlet, pl, employee_user, spv=None, owner=REQUESTER, user=REQUESTER, leave_approver=None,
		department=None, approvers=(), employee_approver=None):
	"""Transitions whose condition passes for the outlet/PL/SPV/employee setup.

	`approvers` are the Department's Leave & Overtime Approvers rows, in order.
	"""
	def get_value(doctype, name, field=None, *args, **kwargs):
		if doctype == "Employee":
			return {"outlet": outlet, "user_id": employee_user, "department": department, "leave_approver": employee_approver}[field]
		if doctype == "Outlet":
			return {"approver_1": pl, "approver_2": spv}[field] if name else None
		if doctype == "Department Approver":
			assert name["parentfield"] == "leave_approvers" and field == "approver"
			rows = approvers if name["parent"] and name["parent"] == department else ()
			return rows[name["idx"] - 1] if name["idx"] <= len(rows) else None
		if doctype == "HR Settings":
			return 0

	doc = frappe._dict(employee="EMP-1", owner=owner, leave_approver=leave_approver)
	with patch("frappe.db.get_value", side_effect=get_value), patch("frappe.session", new=frappe._dict(user=user)):
		return [
			row for row in rows
			if not row["condition"] or safe_eval(row["condition"], get_workflow_safe_globals(), dict(doc=doc))
		]


def available_submissions(**setup):
	"""Actions offered from Open for the outlet/PL/employee setup."""
	rows = [row for row in configuration()["transitions"] if row["state"] == "Open" and row["action"].startswith("Ajukan")]
	return [row["action"] for row in evaluate(rows, **setup)]


def approval_targets(state, role, **setup):
	"""Where Approve at `state` leads for the given approver role and setup."""
	rows = [row for row in configuration()["transitions"] if row["state"] == state and row["action"] == "Approve" and row["allowed"] == role]
	return [row["next_state"] for row in evaluate(rows, **setup)]


def hrd_approval(**setup):
	"""Menunggu HRD -> Approve rows that would let `user` decide."""
	rows = [row for row in configuration()["transitions"] if row["state"] == "Menunggu HRD" and row["action"] == "Approve"]
	return [row for row in evaluate(rows, **setup) if row["allow_self_approval"] or setup["user"] != setup["owner"]]


class TestLeaveWorkflowRouting(unittest.TestCase):
	def test_outlet_employee_goes_to_pl(self):
		self.assertEqual(available_submissions(outlet="OUT-1", pl="pl@example.com", employee_user=REQUESTER), ["Ajukan ke PL"])

	def test_pl_own_leave_skips_pl_stage(self):
		self.assertEqual(available_submissions(outlet="OUT-1", pl=REQUESTER, employee_user=REQUESTER), ["Ajukan ke HRD"])

	def test_outlet_without_pl_goes_to_hrd(self):
		self.assertEqual(available_submissions(outlet="OUT-1", pl=None, employee_user=REQUESTER), ["Ajukan ke HRD"])

	def test_employee_without_user_is_not_mistaken_for_missing_pl(self):
		self.assertEqual(available_submissions(outlet="OUT-1", pl="pl@example.com", employee_user=None, owner="hr@example.com", user="hr@example.com"), ["Ajukan ke PL"])

	def test_company_employee_without_any_approver_goes_to_hrd(self):
		self.assertEqual(available_submissions(outlet=None, pl=None, employee_user=REQUESTER), ["Ajukan ke HRD"])

	def test_hr_can_approve_a_request_it_created_for_someone_else(self):
		self.assertTrue(hrd_approval(outlet="OUT-1", pl=None, employee_user="employee@example.com", owner="hr@example.com", user="hr@example.com"))

	def test_hr_cannot_approve_its_own_leave_even_as_creator(self):
		self.assertFalse(hrd_approval(outlet="OUT-1", pl=None, employee_user="hr@example.com", owner="hr@example.com", user="hr@example.com"))
		self.assertFalse(hrd_approval(outlet="OUT-1", pl=None, employee_user="hr@example.com", owner="other@example.com", user="hr@example.com"))

	def test_no_leave_is_approved_from_open_every_leave_reaches_hrd(self):
		rows = [row for row in configuration()["transitions"] if row["state"] == "Open"]
		self.assertEqual([row for row in rows if row["action"] == "Approve"], [])
		self.assertEqual({row["allowed"] for row in rows if row["action"] == "Reject"}, {"HR Manager", "System Manager"})

	def test_only_the_document_owner_can_submit(self):
		self.assertEqual(available_submissions(outlet="OUT-1", pl=None, employee_user=REQUESTER, owner="other@example.com"), [])


PL_USER, SPV_USER = "pl@example.com", "spv@example.com"


class TestLeaveApprover2Routing(unittest.TestCase):
	def test_pl_is_still_first_when_both_approvers_are_set(self):
		self.assertEqual(available_submissions(outlet="OUT-1", pl=PL_USER, spv=SPV_USER, employee_user=REQUESTER), ["Ajukan ke PL"])

	def test_outlet_with_only_approver_2_goes_to_spv(self):
		self.assertEqual(available_submissions(outlet="OUT-1", pl=None, spv=SPV_USER, employee_user=REQUESTER), ["Ajukan ke SPV"])

	def test_spv_own_leave_without_pl_goes_to_hrd(self):
		self.assertEqual(available_submissions(outlet="OUT-1", pl=None, spv=REQUESTER, employee_user=REQUESTER), ["Ajukan ke HRD"])

	def test_pl_approval_moves_to_spv_only_when_approver_2_is_set(self):
		setup = dict(outlet="OUT-1", pl=PL_USER, employee_user=REQUESTER, user=PL_USER, leave_approver=PL_USER)
		self.assertEqual(approval_targets("Menunggu PL", "PL Outlet", spv=SPV_USER, **setup), ["Menunggu SPV"])
		self.assertEqual(approval_targets("Menunggu PL", "PL Outlet", spv=None, **setup), ["Menunggu HRD"])

	def test_same_person_as_approver_1_and_2_is_asked_once(self):
		setup = dict(outlet="OUT-1", pl=PL_USER, spv=PL_USER, employee_user=REQUESTER, user=PL_USER, leave_approver=PL_USER)
		self.assertEqual(approval_targets("Menunggu PL", "PL Outlet", **setup), ["Menunggu HRD"])

	def test_spv_leave_skips_its_own_stage_after_the_pl(self):
		setup = dict(outlet="OUT-1", pl=PL_USER, spv=REQUESTER, employee_user=REQUESTER, user=PL_USER, leave_approver=PL_USER)
		self.assertEqual(approval_targets("Menunggu PL", "PL Outlet", **setup), ["Menunggu HRD"])

	def test_only_the_recorded_approver_2_decides_the_spv_stage(self):
		setup = dict(outlet="OUT-1", pl=PL_USER, spv=SPV_USER, employee_user=REQUESTER, leave_approver=SPV_USER)
		self.assertEqual(approval_targets("Menunggu SPV", "SPV Outlet", user=SPV_USER, **setup), ["Menunggu HRD"])
		self.assertEqual(approval_targets("Menunggu SPV", "SPV Outlet", user="other.spv@example.com", **setup), [])


APPROVER_1, APPROVER_2 = "approver1@example.com", "approver2@example.com"
DEPARTMENT = dict(outlet=None, pl=None, department="Finance")


def open_approvals(**setup):
	"""Open -> Approve rows (the one-level company route) available to `user`."""
	rows = [row for row in configuration()["transitions"] if row["state"] == "Open" and row["action"] == "Approve"]
	return [row["allowed"] for row in evaluate(rows, **setup)]


class TestDepartmentApproverRouting(unittest.TestCase):
	"""Non-outlet employees whose Department lists Leave & Overtime Approvers get the outlet's two optional stages."""

	def test_department_employee_goes_to_approver_1(self):
		self.assertEqual(available_submissions(**DEPARTMENT, approvers=(APPROVER_1, APPROVER_2), employee_user=REQUESTER), ["Ajukan ke Approver 1"])

	def test_approver_1_own_leave_skips_its_stage(self):
		self.assertEqual(available_submissions(**DEPARTMENT, approvers=(REQUESTER, APPROVER_2), employee_user=REQUESTER), ["Ajukan ke Approver 2"])
		self.assertEqual(available_submissions(**DEPARTMENT, approvers=(REQUESTER,), employee_user=REQUESTER), ["Ajukan ke HRD"])

	def test_department_without_a_table_uses_the_employee_leave_approver_then_hrd(self):
		setup = dict(**DEPARTMENT, employee_approver=APPROVER_1, employee_user=REQUESTER)
		self.assertEqual(available_submissions(**setup), ["Ajukan ke Approver 1"])
		self.assertEqual(approval_targets("Menunggu Approver 1", "Leave Approver", user=APPROVER_1, leave_approver=APPROVER_1, **setup), ["Menunggu HRD"])

	def test_the_employee_leave_approver_own_leave_goes_to_hrd(self):
		self.assertEqual(available_submissions(**DEPARTMENT, employee_approver=REQUESTER, employee_user=REQUESTER), ["Ajukan ke HRD"])

	def test_a_department_table_wins_over_the_employee_leave_approver(self):
		setup = dict(**DEPARTMENT, approvers=(APPROVER_1,), employee_approver="other@example.com", employee_user=REQUESTER)
		self.assertEqual(approval_targets("Menunggu Approver 1", "Leave Approver", user="other@example.com", leave_approver="other@example.com", **setup), [])
		self.assertEqual(approval_targets("Menunggu Approver 1", "Leave Approver", user=APPROVER_1, leave_approver=APPROVER_1, **setup), ["Menunggu HRD"])

	def test_department_without_any_approver_goes_to_hrd(self):
		self.assertEqual(available_submissions(**DEPARTMENT, employee_user=REQUESTER), ["Ajukan ke HRD"])

	def test_tiered_department_has_no_one_level_approval(self):
		setup = dict(**DEPARTMENT, approvers=(APPROVER_1,), employee_user="employee@example.com", owner="employee@example.com", user=APPROVER_1, leave_approver=APPROVER_1)
		self.assertEqual(open_approvals(**setup), [])

	def test_approver_1_moves_to_approver_2_only_when_it_is_set(self):
		setup = dict(**DEPARTMENT, employee_user=REQUESTER, user=APPROVER_1, leave_approver=APPROVER_1)
		self.assertEqual(approval_targets("Menunggu Approver 1", "Leave Approver", approvers=(APPROVER_1, APPROVER_2), **setup), ["Menunggu Approver 2"])
		self.assertEqual(approval_targets("Menunggu Approver 1", "Leave Approver", approvers=(APPROVER_1,), **setup), ["Menunggu HRD"])

	def test_same_person_on_both_rows_or_approver_2_own_leave_is_asked_once(self):
		setup = dict(**DEPARTMENT, user=APPROVER_1, leave_approver=APPROVER_1)
		self.assertEqual(approval_targets("Menunggu Approver 1", "Leave Approver", approvers=(APPROVER_1, APPROVER_1), employee_user=REQUESTER, **setup), ["Menunggu HRD"])
		self.assertEqual(approval_targets("Menunggu Approver 1", "Leave Approver", approvers=(APPROVER_1, REQUESTER), employee_user=REQUESTER, **setup), ["Menunggu HRD"])

	def test_only_the_recorded_approver_decides_each_stage(self):
		setup = dict(**DEPARTMENT, approvers=(APPROVER_1, APPROVER_2), employee_user=REQUESTER)
		self.assertEqual(approval_targets("Menunggu Approver 1", "Leave Approver", user=APPROVER_2, leave_approver=APPROVER_1, **setup), [])
		self.assertEqual(approval_targets("Menunggu Approver 2", "Leave Approver", user=APPROVER_2, leave_approver=APPROVER_2, **setup), ["Menunggu HRD"])
		self.assertEqual(approval_targets("Menunggu Approver 2", "Leave Approver", user=APPROVER_1, leave_approver=APPROVER_2, **setup), [])

	def test_approver_never_approves_own_leave(self):
		setup = dict(**DEPARTMENT, approvers=(APPROVER_1, APPROVER_2), employee_user=APPROVER_2, user=APPROVER_2, leave_approver=APPROVER_2)
		self.assertEqual(approval_targets("Menunggu Approver 2", "Leave Approver", **setup), [])

	def test_hrd_decides_department_leave_but_not_its_own(self):
		setup = dict(**DEPARTMENT, approvers=(APPROVER_1,), owner="employee@example.com", user="hr@example.com")
		self.assertTrue(hrd_approval(employee_user="employee@example.com", **setup))
		self.assertFalse(hrd_approval(employee_user="hr@example.com", **setup))

	def test_hrd_still_decides_after_the_department_table_is_emptied(self):
		self.assertTrue(hrd_approval(**DEPARTMENT, employee_user="employee@example.com", owner="employee@example.com", user="hr@example.com"))

	def test_department_stages_are_edited_by_leave_approvers(self):
		rows = {row["state"]: row for row in configuration()["states"]}
		for state in ("Menunggu Approver 1", "Menunggu Approver 2"):
			# the leave approver is handed over in leave_approver.hand_over_to_approver (an expression would not fit)
			self.assertEqual((rows[state]["allow_edit"], rows[state]["update_field"], rows[state]["evaluate_as_expression"]), ("Leave Approver", "status", 0))

	def test_every_state_update_value_fits_its_140_character_field(self):
		for row in configuration()["states"]:
			self.assertLessEqual(len(row["update_value"]), 140, row["state"])

	def test_outlet_routes_are_not_changed(self):
		outlet = dict(outlet="OUT-1", pl=PL_USER, spv=SPV_USER, employee_user=REQUESTER, department="Finance", approvers=(APPROVER_1,))
		self.assertEqual(available_submissions(**outlet), ["Ajukan ke PL"])
		self.assertEqual(approval_targets("Menunggu PL", "PL Outlet", user=PL_USER, leave_approver=PL_USER, **outlet), ["Menunggu SPV"])

	def test_a_user_holding_every_role_steps_in_when_a_department_stage_is_stuck(self):
		setup = dict(**DEPARTMENT, approvers=(APPROVER_1, APPROVER_2), employee_user=REQUESTER, user="Administrator", leave_approver=APPROVER_1)
		self.assertEqual(approval_targets("Menunggu Approver 1", "HR Manager", **setup), ["Menunggu Approver 2"])
		self.assertEqual(approval_targets("Menunggu Approver 1", "HR Manager", **{**setup, "leave_approver": "Administrator"}), [])

	def test_spv_own_leave_goes_straight_to_hrd_skipping_the_lower_leader(self):
		self.assertEqual(available_submissions(**DEPARTMENT, approvers=(APPROVER_1, REQUESTER), employee_user=REQUESTER), ["Ajukan ke HRD"])

	def test_employee_without_a_user_is_not_mistaken_for_a_missing_spv(self):
		setup = dict(**DEPARTMENT, approvers=(APPROVER_1,), employee_user=None, owner="hr@example.com", user="hr@example.com")
		self.assertEqual(available_submissions(**setup), ["Ajukan ke Approver 1"])

	def test_outlet_spv_own_leave_still_goes_through_the_pl(self):
		self.assertEqual(available_submissions(outlet="OUT-1", pl=PL_USER, spv=REQUESTER, employee_user=REQUESTER), ["Ajukan ke PL"])
