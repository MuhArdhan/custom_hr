"""Department Leave & Overtime Approvers: rows 1 and 2 are the two optional approval stages."""

import unittest
from unittest.mock import patch

import frappe

from custom_hr.services import department_approvers as svc

BOTH = ["Leave Approver", "Overtime Approver"]


def department(*approvers):
	return frappe._dict(leave_approvers=[frappe._dict(approver=user) for user in approvers])


class TestValidateDepartmentApprovers(unittest.TestCase):
	def validate(self, doc, roles=None):
		with patch("frappe.get_roles", side_effect=lambda user: (roles or {}).get(user, BOTH)):
			svc.validate_department_approvers(doc)

	def test_up_to_two_approvers_with_both_roles_are_accepted(self):
		for doc in (department(), department("a@example.com"), department("a@example.com", "b@example.com")):
			self.validate(doc)

	def test_a_third_row_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "maksimal 2 baris"):
			self.validate(department("a@example.com", "b@example.com", "c@example.com"))

	def test_an_approver_without_both_roles_is_refused_by_name(self):
		for roles, missing in ((["Leave Approver"], "Overtime Approver"), (["Overtime Approver"], "Leave Approver")):
			with self.subTest(missing=missing), self.assertRaisesRegex(frappe.ValidationError, f"b@example.com belum punya role {missing}"):
				self.validate(department("a@example.com", "b@example.com"), roles={"b@example.com": roles})

	def test_blank_rows_do_not_count(self):
		self.validate(department("a@example.com", None, "b@example.com"))

	def test_validate_runs_on_department_save(self):
		hooks = frappe.get_hooks("doc_events")["Department"]["validate"]
		self.assertIn("custom_hr.services.department_approvers.validate_department_approvers", hooks)


class TestDepartmentApproverRows(unittest.TestCase):
	def test_rows_come_in_order_and_at_most_two(self):
		with patch("frappe.get_all", return_value=["a@example.com", "b@example.com"]) as get_all:
			self.assertEqual(svc.department_approvers("Finance"), ["a@example.com", "b@example.com"])
		kwargs = get_all.call_args.kwargs
		self.assertEqual((kwargs["filters"]["parentfield"], kwargs["order_by"], kwargs["limit"]), ("leave_approvers", "idx", 2))

	def test_no_department_has_no_approvers(self):
		with patch("frappe.get_all", side_effect=AssertionError("no lookup")):
			self.assertEqual(svc.department_approvers(None), [])


class TestWorkingCalendarCompanies(unittest.TestCase):
	"""The Working Calendar company filter offers an approver's outlets and the companies of their departments."""

	def companies(self, outlets, departments, companies):
		from custom_hr.api import leave_calendar

		def get_all(doctype, filters=None, **kwargs):
			if doctype == "Department Approver":
				self.assertEqual((filters["approver"], filters["parentfield"], filters["idx"]), ("a1@example.com", "leave_approvers", ["<=", 2]))
				return departments
			if doctype == "Department":
				return [companies[name] for name in filters["name"][1]]
			raise AssertionError(doctype)

		with patch("frappe.session", new=frappe._dict(user="a1@example.com")), \
			patch("custom_hr.api.overtime._their_outlets", return_value=outlets), patch("frappe.get_all", side_effect=get_all):
			return leave_calendar.approver_companies()

	def test_outlets_and_department_companies_are_merged_once(self):
		self.assertEqual(self.companies(["Outlet A"], ["Finance", "IT"], {"Finance": "PT Kantor", "IT": "PT Kantor"}), ["Outlet A", "PT Kantor"])

	def test_a_department_only_approver_still_gets_its_company(self):
		self.assertEqual(self.companies([], ["Finance"], {"Finance": "PT Kantor"}), ["PT Kantor"])

	def test_no_approver_rows_means_no_companies(self):
		self.assertEqual(self.companies([], [], {}), [])


class TestReviewFixes(unittest.TestCase):
	def test_the_same_person_on_both_rows_is_refused(self):
		with patch("frappe.get_roles", return_value=BOTH), self.assertRaisesRegex(frappe.ValidationError, "lebih dari sekali"):
			svc.validate_department_approvers(department("a@example.com", "a@example.com"))

	def test_rows_are_read_by_idx_1_and_2_like_the_workflow(self):
		with patch("frappe.get_all", return_value=[]) as get_all:
			svc.department_approvers("Finance")
		self.assertEqual(get_all.call_args.kwargs["filters"]["idx"], ["in", [1, 2]])

	def test_the_stuck_stage_override_needs_system_manager_not_just_leave_approver(self):
		from custom_hr.services.approval_override import DEPARTMENT_LEAVE_ROLES

		self.assertEqual(set(DEPARTMENT_LEAVE_ROLES), {"System Manager", "HR Manager"})


class TestStageApprovers(unittest.TestCase):
	def stages(self, rows, leave_approver=None):
		with patch("frappe.db.get_value", return_value=("Finance", leave_approver)), patch.object(svc, "department_approvers", return_value=rows):
			return svc.stage_approvers("E1")

	def test_the_department_table_comes_first(self):
		self.assertEqual(self.stages(["a1@example.com", "a2@example.com"], leave_approver="other@example.com"), ["a1@example.com", "a2@example.com"])

	def test_without_a_table_the_employee_leave_approver_is_stage_1(self):
		self.assertEqual(self.stages([], leave_approver="la@example.com"), ["la@example.com"])

	def test_nobody_means_straight_to_hrd(self):
		self.assertEqual(self.stages([], leave_approver=None), [])
