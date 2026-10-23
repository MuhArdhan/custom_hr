"""Submission routing of the native leave Workflow; conditions are evaluated, nothing is written."""

import unittest
from unittest.mock import patch

import frappe
from frappe.model.workflow import get_workflow_safe_globals
from frappe.utils.safe_exec import safe_eval

from custom_hr.patches.setup_native_leave_workflow import configuration

REQUESTER = "requester@example.com"


def evaluate(rows, *, outlet, pl, employee_user, owner=REQUESTER, user=REQUESTER):
	"""Transitions whose condition passes for the outlet/PL/employee setup."""
	def get_value(doctype, name, field=None, *args, **kwargs):
		if doctype == "Employee":
			return {"outlet": outlet, "user_id": employee_user}[field]
		if doctype == "Outlet":
			return pl if name else None
		if doctype == "HR Settings":
			return 0

	doc = frappe._dict(employee="EMP-1", owner=owner, leave_approver=None)
	with patch("frappe.db.get_value", side_effect=get_value), patch("frappe.session", new=frappe._dict(user=user)):
		return [
			row for row in rows
			if not row["condition"] or safe_eval(row["condition"], get_workflow_safe_globals(), dict(doc=doc))
		]


def available_submissions(**setup):
	"""Actions offered from Open for the outlet/PL/employee setup."""
	rows = [row for row in configuration()["transitions"] if row["state"] == "Open" and row["action"].startswith("Ajukan")]
	return [row["action"] for row in evaluate(rows, **setup)]


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

	def test_company_employee_has_no_outlet_submission(self):
		self.assertEqual(available_submissions(outlet=None, pl=None, employee_user=REQUESTER), [])

	def test_hr_can_approve_a_request_it_created_for_someone_else(self):
		self.assertTrue(hrd_approval(outlet="OUT-1", pl=None, employee_user="employee@example.com", owner="hr@example.com", user="hr@example.com"))

	def test_hr_cannot_approve_its_own_leave_even_as_creator(self):
		self.assertFalse(hrd_approval(outlet="OUT-1", pl=None, employee_user="hr@example.com", owner="hr@example.com", user="hr@example.com"))
		self.assertFalse(hrd_approval(outlet="OUT-1", pl=None, employee_user="hr@example.com", owner="other@example.com", user="hr@example.com"))

	def test_company_hr_can_approve_what_it_created_but_not_a_leave_approver(self):
		rows = [row for row in configuration()["transitions"] if row["state"] == "Open" and row["action"] == "Approve"]
		by_role = {row["allowed"]: row["allow_self_approval"] for row in rows}
		self.assertEqual(by_role, {"Leave Approver": 0, "HR Manager": 1, "System Manager": 1})

	def test_only_the_document_owner_can_submit(self):
		self.assertEqual(available_submissions(outlet="OUT-1", pl=None, employee_user=REQUESTER, owner="other@example.com"), [])
