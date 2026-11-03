"""Non-outlet overtime: rows 1 and 2 of the Department's Leave & Overtime Approvers play Approver 1 and 2."""

import json
import os
import unittest
from unittest.mock import patch

import frappe

from custom_hr.api import overtime as access

MODULE = "custom_hr.hrm.doctype.overtime_request.overtime_request"
WORKFLOW = os.path.join(os.path.dirname(__file__), "..", "fixtures", "workflow.json")


def request(*employees):
	doc = frappe.get_doc({"doctype": "Overtime Request", "company": "PT Kantor", "employees": [{"employee": e} for e in employees]})
	doc.set("__islocal", 1)  # as insert() marks it
	return doc


class TestDepartmentApproversOnRequest(unittest.TestCase):
	def fetch(self, doc, departments, rows):
		with patch("frappe.db.exists", return_value=None), \
			patch("frappe.db.get_value", side_effect=lambda dt, name, field=None, *a, **k: departments[name] if (dt, field) == ("Employee", "department") else None), \
			patch(f"{MODULE}.department_approvers", side_effect=lambda department: rows.get(department, [])):
			doc.fetch_outlet_details()
		return doc

	def test_rows_1_and_2_become_approver_1_and_2(self):
		doc = self.fetch(request("E1"), {"E1": "Finance"}, {"Finance": ["a1@example.com", "a2@example.com"]})
		self.assertEqual((doc.outlet, doc.approver_1, doc.approver_2), (None, "a1@example.com", "a2@example.com"))

	def test_a_single_row_leaves_approver_2_empty(self):
		doc = self.fetch(request("E1"), {"E1": "Finance"}, {"Finance": ["a1@example.com"]})
		self.assertEqual((doc.approver_1, doc.approver_2), ("a1@example.com", None))

	def test_department_without_approvers_still_goes_straight_to_hrd(self):
		doc = self.fetch(request("E1"), {"E1": "Finance"}, {})
		self.assertEqual((doc.approver_1, doc.approver_2), (None, None))
		with patch("frappe.session", new=frappe._dict(user="employee@example.com")):
			self.assertEqual(doc.initial_state(), "Menunggu HRD")

	def test_employees_with_different_department_approvers_are_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "approver departemen yang sama"):
			self.fetch(request("E1", "E2"), {"E1": "Finance", "E2": "IT"}, {"Finance": ["a1@example.com"], "IT": ["b1@example.com"]})

	def test_departments_naming_the_same_approvers_may_share_a_request(self):
		doc = self.fetch(request("E1", "E2"), {"E1": "Finance", "E2": "Tax"}, {"Finance": ["a1@example.com"], "Tax": ["a1@example.com"]})
		self.assertEqual(doc.approver_1, "a1@example.com")

	def test_approver_1_own_request_skips_its_stage(self):
		doc = self.fetch(request("E1"), {"E1": "Finance"}, {"Finance": ["a1@example.com", "a2@example.com"]})
		with patch("frappe.session", new=frappe._dict(user="a1@example.com")):
			self.assertEqual(doc.initial_state(), "Menunggu SPV")

	def test_saved_request_keeps_its_recorded_approvers(self):
		doc = request("E1")
		doc.name, doc.approver_1 = "OT-1", "old@example.com"
		doc.set("__islocal", 0)
		self.fetch(doc, {"E1": "Finance"}, {"Finance": ["new@example.com"]})
		self.assertEqual(doc.approver_1, "old@example.com")


class TestOvertimeApproverRole(unittest.TestCase):
	def workflow(self):
		return next(row for row in json.load(open(WORKFLOW)) if row["document_type"] == "Overtime Request")

	def test_overtime_approver_decides_the_non_outlet_stages(self):
		rows = {(t["state"], t["action"], t["next_state"]): t for t in self.workflow()["transitions"] if t["allowed"] == "Overtime Approver"}
		self.assertEqual(set(rows), {
			("Menunggu Leader", "Setujui", "Menunggu SPV"), ("Menunggu Leader", "Setujui", "Menunggu HRD"), ("Menunggu Leader", "Tolak", "Ditolak"),
			("Menunggu SPV", "Setujui", "Menunggu HRD"), ("Menunggu SPV", "Tolak", "Ditolak"),
		})
		for row in rows.values():
			self.assertTrue(row["condition"].startswith("not doc.outlet and "), row["condition"])
		self.assertIn("doc.approver_1 == frappe.session.user", rows[("Menunggu Leader", "Tolak", "Ditolak")]["condition"])
		self.assertIn("doc.approver_2 == frappe.session.user", rows[("Menunggu SPV", "Tolak", "Ditolak")]["condition"])

	def test_outlet_transitions_only_serve_outlet_requests(self):
		outlet = [t for t in self.workflow()["transitions"] if t["allowed"] in ("Outlet Leader", "SPV Outlet")]
		self.assertEqual(len(outlet), 5)
		self.assertTrue(all(t["condition"].startswith("doc.outlet and ") for t in outlet))

	def test_one_button_per_action_for_a_user_holding_outlet_and_department_roles(self):
		# a Leader/SPV Outlet who is also a Department approver matched both rows and saw Setujui twice
		from frappe.model.workflow import get_workflow_safe_globals
		from frappe.utils.safe_exec import safe_eval

		rows = [t for t in self.workflow()["transitions"] if t["allowed"] in ("Outlet Leader", "SPV Outlet", "Overtime Approver")]
		for outlet in ("Outlet A", None):
			for user, state in (("a1@example.com", "Menunggu Leader"), ("a2@example.com", "Menunggu SPV")):
				doc = frappe._dict(outlet=outlet, approver_1="a1@example.com", approver_2="a2@example.com")
				with patch("frappe.session", new=frappe._dict(user=user)):
					passing = [t for t in rows if t["state"] == state and safe_eval(t["condition"], get_workflow_safe_globals(), dict(doc=doc))]
				actions = [t["action"] for t in passing]
				self.assertEqual(sorted(actions), sorted(set(actions)), (outlet, state, passing))
				self.assertEqual({t["allowed"] for t in passing}, {"Overtime Approver"} if not outlet else ({"Outlet Leader"} if state == "Menunggu Leader" else {"SPV Outlet"}))

	def test_overtime_approver_can_open_requests_and_the_overtime_list(self):
		for doctype, rights in (("Overtime Request", ("read", "write", "create")), ("Overtime List", ("read",))):
			perm = next((p for p in frappe.get_meta(doctype).permissions if p.role == "Overtime Approver"), None)
			self.assertIsNotNone(perm, doctype)
			self.assertTrue(all(perm.get(right) for right in rights), doctype)


class TestDepartmentApproverVisibility(unittest.TestCase):
	def test_recorded_approver_sees_non_outlet_requests_without_any_outlet(self):
		with patch(f"{access.__name__}._sees_all", return_value=False), patch(f"{access.__name__}._their_outlets", return_value=[]):
			condition = access.get_permission_query_conditions("a1@example.com")
		self.assertIn("`tabOvertime Request`.`approver_1` = 'a1@example.com'", condition)
		self.assertIn("`tabOvertime Request`.`approver_2` = 'a1@example.com'", condition)
		self.assertNotIn("1=0", condition)

	def test_outlet_scope_is_kept_alongside(self):
		with patch(f"{access.__name__}._sees_all", return_value=False), patch(f"{access.__name__}._their_outlets", return_value=["Outlet A"]):
			condition = access.get_permission_query_conditions("leader@example.com")
		self.assertIn("`tabOvertime Request`.`outlet` in ('Outlet A')", condition)

	def test_overtime_list_rows_follow_their_request_approvers(self):
		with patch(f"{access.__name__}._sees_all", return_value=False), patch(f"{access.__name__}._their_outlets", return_value=[]):
			condition = access.get_list_permission_query_conditions("a1@example.com")
		self.assertIn("`tabOvertime List`.`overtime_request` in (select", condition)
		self.assertIn("approver_1` = 'a1@example.com'", condition)

	def test_hr_still_sees_everything(self):
		with patch(f"{access.__name__}._sees_all", return_value=True):
			self.assertEqual(access.get_permission_query_conditions("hr@example.com"), "")


class TestOpeningANonOutletRequest(unittest.TestCase):
	"""Without an outlet to scope by, only the request's own approvers (and its creator) open it by name."""

	def allowed(self, user, **doc):
		with patch(f"{access.__name__}._sees_all", return_value=False), patch(f"{access.__name__}._their_outlets", return_value=["Outlet A"]):
			return access.has_permission(frappe._dict(name="OT-1", **doc), user=user)

	def test_recorded_approvers_and_creator_open_it(self):
		doc = dict(outlet=None, approver_1="a1@example.com", approver_2="a2@example.com", owner="employee@example.com")
		for user in ("a1@example.com", "a2@example.com", "employee@example.com"):
			self.assertTrue(self.allowed(user, **doc), user)

	def test_another_departments_approver_does_not(self):
		self.assertFalse(self.allowed("other@example.com", outlet=None, approver_1="a1@example.com", approver_2=None, owner="employee@example.com"))

	def test_outlet_requests_keep_the_outlet_rule(self):
		self.assertTrue(self.allowed("leader@example.com", outlet="Outlet A", approver_1="x@example.com"))
		self.assertFalse(self.allowed("leader@example.com", outlet="Outlet B", approver_1="x@example.com"))

	def test_an_overtime_list_row_follows_its_requests_approvers(self):
		row = dict(doctype="Overtime List", outlet=None, overtime_request="OT-1", owner="hr@example.com")
		request = ("a1@example.com", None, "employee@example.com")
		with patch("frappe.db.get_value", return_value=request) as read:
			self.assertTrue(self.allowed("a1@example.com", **row))
			self.assertFalse(self.allowed("other@example.com", **row))
		self.assertEqual(read.call_args.args[:2], ("Overtime Request", "OT-1"))


class TestReviewFixes(unittest.TestCase):
	def test_saved_request_cannot_have_its_approvers_rewritten(self):
		# read_only is browser-only: approver 2 could otherwise set approver_1 to itself and approve both stages
		doc = request("E1")
		doc.name, doc.approver_1, doc.approver_2 = "OT-1", "self@example.com", None
		doc.set("__islocal", 0)
		before = frappe._dict(approver_1="a1@example.com", approver_2="a2@example.com")
		with patch.object(type(doc), "get_doc_before_save", return_value=before):
			doc.keep_recorded_approvers()
		self.assertEqual((doc.approver_1, doc.approver_2), ("a1@example.com", "a2@example.com"))

	def test_overtime_approver_can_read_the_linked_masters(self):
		rows = json.load(open(os.path.join(os.path.dirname(__file__), "..", "fixtures", "custom_docperm.json")))
		granted = {row["parent"] for row in rows if row["role"] == "Overtime Approver" and row["read"]}
		self.assertEqual(granted, {"Employee", "Overtime Type", "Shift Type"})

	def test_overtime_report_lists_requests_naming_the_approver(self):
		from custom_hr.hrm.report.laporan_lembur import laporan_lembur

		path = os.path.join(os.path.dirname(laporan_lembur.__file__), "laporan_lembur.json")
		self.assertIn("Overtime Approver", {row["role"] for row in json.load(open(path))["roles"]})
		with patch.object(laporan_lembur, "_sees_all", return_value=False), patch.object(laporan_lembur, "_their_outlets", return_value=[]), \
			patch("frappe.session", new=frappe._dict(user="a1@example.com")), patch("frappe.db.sql", return_value=[]) as sql:
			laporan_lembur.get_data(frappe._dict())
		query, values = sql.call_args.args[:2]
		self.assertIn("otr.approver_1 = %(user)s or otr.approver_2 = %(user)s", query)
		self.assertEqual(values.user, "a1@example.com")


class TestApproverWhoIsAlsoAnEmployee(unittest.TestCase):
	def test_team_rows_do_not_hide_the_request_from_an_approver_with_employee_user_permission(self):
		# ERPNext gives every linked Employee a User Permission on itself; Frappe applies it to child-table links too,
		# so a Leader/SPV/department approver could list a team request but not open it (403).
		field = frappe.get_meta("Overtime Request Employee").get_field("employee")
		self.assertTrue(field.ignore_user_permissions)
		self.assertFalse(frappe.get_meta("Overtime Request").has_field("employee"))  # access stays role + approver scoped


class TestSpvOwnOvertime(unittest.TestCase):
	def test_department_spv_own_overtime_goes_straight_to_hrd(self):
		doc = request("E1")
		doc.outlet, doc.approver_1, doc.approver_2 = None, "a1@example.com", "a2@example.com"
		with patch("frappe.session", new=frappe._dict(user="a2@example.com")):
			self.assertEqual(doc.initial_state(), "Menunggu HRD")

	def test_outlet_spv_own_overtime_keeps_the_leader_stage(self):
		doc = request("E1")
		doc.outlet, doc.approver_1, doc.approver_2 = "Outlet A", "a1@example.com", "a2@example.com"
		with patch("frappe.session", new=frappe._dict(user="a2@example.com")):
			self.assertEqual(doc.initial_state(), "Menunggu Leader")
