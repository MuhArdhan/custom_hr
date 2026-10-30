"""Outlet employees get their Outlet's Approver 1 as Leave Approver; native sources win."""

import unittest
from unittest.mock import patch

import frappe

from custom_hr.services import leave_approver as svc

HRMS_APPROVER = "custom_hr.services.leave_approver.get_employee_leave_approver"


class TestLeaveApprover(unittest.TestCase):
	def employee(self, outlet, approver_1="pl@example.com"):
		def get_value(doctype, name, field=None, *args, **kwargs):
			if doctype == "Employee":
				return outlet
			if doctype == "Outlet":
				return approver_1
		return patch("frappe.db.get_value", side_effect=get_value)

	def test_outlet_employee_without_native_approver_gets_the_outlet_approver(self):
		with patch(HRMS_APPROVER, return_value=None), self.employee("Outlet A"):
			self.assertEqual(svc.get_leave_approver("E1"), "pl@example.com")

	def test_native_employee_or_department_approver_wins(self):
		with patch(HRMS_APPROVER, return_value="boss@example.com"), self.employee("Outlet A"):
			self.assertEqual(svc.get_leave_approver("E1"), "boss@example.com")

	def test_employee_without_outlet_keeps_the_native_result(self):
		with patch(HRMS_APPROVER, return_value=None), self.employee(None):
			self.assertIsNone(svc.get_leave_approver("E1"))

	def test_outlet_without_approver_returns_nothing(self):
		with patch(HRMS_APPROVER, return_value=None), self.employee("Outlet A", approver_1=None):
			self.assertFalse(svc.get_leave_approver("E1"))

	def test_hook_fills_an_empty_approver_only(self):
		with patch(HRMS_APPROVER, return_value=None), self.employee("Outlet A"):
			doc = frappe._dict(employee="E1", leave_approver=None)
			svc.fill_leave_approver(doc)
			self.assertEqual(doc.leave_approver, "pl@example.com")
			doc = frappe._dict(employee="E1", leave_approver="chosen@example.com")
			svc.fill_leave_approver(doc)
			self.assertEqual(doc.leave_approver, "chosen@example.com")

	def test_stage_label_names_the_approver(self):
		doc = frappe._dict(leave_approver_name="Budi", leave_approver="pl@example.com")
		self.assertEqual(svc.stage_label("Menunggu PL", doc), "Waiting for Budi")
		self.assertEqual(svc.stage_label("Menunggu PL", frappe._dict(leave_approver=None)), "Menunggu PL")
		self.assertEqual(svc.stage_label("Menunggu HRD", doc), "Menunggu HRD")
		self.assertEqual(svc.stage_label("Open", doc), "Open")


class TestMobileApprovalDetails(unittest.TestCase):
	"""The HRMS mobile app reads hrms.api.get_leave_approval_details instead of the desk lookup."""

	ORIGINAL = "custom_hr.services.leave_approver.hrms_get_leave_approval_details"

	def run_details(self, native, outlet_approver="pl@example.com"):
		def get_value(doctype, name, field=None, *args, **kwargs):
			if doctype == "Employee":
				return "Outlet A"
			if doctype == "Outlet":
				return outlet_approver
			return "Budi"  # User.full_name
		with patch(self.ORIGINAL, return_value=native), patch(HRMS_APPROVER, return_value=None), patch("frappe.db.get_value", side_effect=get_value):
			return svc.get_leave_approval_details("E1")

	def test_outlet_approver_is_selected_and_listed_when_there_is_no_native_one(self):
		native = dict(leave_approver=None, leave_approver_name=None, department_approvers=[], is_mandatory=1)
		result = self.run_details(native)
		self.assertEqual((result["leave_approver"], result["leave_approver_name"]), ("pl@example.com", "Budi"))
		self.assertEqual(result["department_approvers"], [{"name": "pl@example.com", "full_name": "Budi"}])
		self.assertEqual(result["is_mandatory"], 1)

	def test_native_approver_is_left_untouched(self):
		native = dict(leave_approver="boss@example.com", leave_approver_name="Boss", department_approvers=[{"name": "boss@example.com", "full_name": "Boss"}], is_mandatory=1)
		self.assertEqual(self.run_details(native), native)

	def test_outlet_without_approver_changes_nothing(self):
		native = dict(leave_approver=None, leave_approver_name=None, department_approvers=[], is_mandatory=1)
		self.assertEqual(self.run_details(native, outlet_approver=None), native)


class TestSubmitToApprover(unittest.TestCase):
	"""Saving a new leave is enough: it goes to the approver without the extra 'Ajukan' click."""

	def run_hook(self, actions, apply_side_effect=None):
		transitions = [frappe._dict(action=a) for a in actions]
		with patch("custom_hr.services.leave_approver.get_transitions", return_value=transitions), \
			patch("custom_hr.services.leave_approver.apply_workflow", side_effect=apply_side_effect) as apply:
			svc.submit_to_approver(frappe._dict(name="LEAVE-1"))
		return apply

	def test_submits_to_the_pl(self):
		apply = self.run_hook(["Ajukan ke PL"])
		self.assertEqual(apply.call_args.args[1], "Ajukan ke PL")

	def test_submits_to_hrd_when_there_is_no_pl(self):
		self.assertEqual(self.run_hook(["Ajukan ke HRD"]).call_args.args[1], "Ajukan ke HRD")

	def test_non_outlet_leave_stays_open_for_its_native_approver(self):
		self.run_hook(["Approve", "Reject"]).assert_not_called()

	def test_a_refused_transition_leaves_the_leave_open_instead_of_failing_the_save(self):
		self.run_hook(["Ajukan ke PL"], apply_side_effect=frappe.ValidationError("no"))


class TestHandOverToApprover2(unittest.TestCase):
	def run_hook(self, state, leave_approver="pl@example.com", approver_2="spv@example.com"):
		doc = frappe._dict(doctype="Leave Application", name="LA-1", employee="E1", leave_approver=leave_approver, leave_workflow_state=state)
		doc.db_set = lambda values: dict.update(doc, values)
		with patch("frappe.db.get_value", side_effect=lambda dt, *a, **k: "Outlet A" if dt == "Employee" else approver_2), patch("frappe.utils.get_fullname", return_value="Siti"), patch("frappe.share.add_docshare") as share:
			svc.hand_over_to_approver_2(doc)
		return doc, share

	def test_spv_stage_makes_approver_2_the_leave_approver_and_shares_the_request(self):
		doc, share = self.run_hook("Menunggu SPV")
		self.assertEqual((doc.leave_approver, doc.leave_approver_name), ("spv@example.com", "Siti"))
		self.assertEqual(share.call_args.args[:3], ("Leave Application", "LA-1", "spv@example.com"))

	def test_other_stages_and_an_already_set_approver_are_left_alone(self):
		for state, current in (("Menunggu PL", "pl@example.com"), ("Menunggu SPV", "spv@example.com")):
			with self.subTest(state=state):
				doc, share = self.run_hook(state, leave_approver=current)
				self.assertEqual(doc.leave_approver, current)
				share.assert_not_called()


class TestOutletApproverFallback(unittest.TestCase):
	def lookup(self, approver_1, approver_2):
		values = {"approver_1": approver_1, "approver_2": approver_2}
		get_value = lambda doctype, name, field=None, *a, **k: "Outlet A" if doctype == "Employee" else values[field]
		with patch(HRMS_APPROVER, return_value=None), patch("frappe.db.get_value", side_effect=get_value):
			return svc.get_leave_approver("E1")

	def test_approver_1_first_then_approver_2_then_nothing(self):
		self.assertEqual(self.lookup("pl@example.com", "spv@example.com"), "pl@example.com")
		self.assertEqual(self.lookup(None, "spv@example.com"), "spv@example.com")
		self.assertFalse(self.lookup(None, None))
