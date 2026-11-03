"""The patch that brings tiered department approval to an installed site; nothing is written."""

import unittest
from unittest.mock import patch

import frappe

from custom_hr.patches import add_department_approval as patch_module
from custom_hr.patches.setup_native_leave_workflow import OUTLET, configuration

COMPANY_NOT_SELF = '(not frappe.db.get_value("HR Settings", None, "prevent_self_leave_approval") or frappe.db.get_value("Employee", doc.employee, "user_id") != frappe.session.user)'


def installed(rows):
	workflow = frappe._dict(transitions=[frappe._dict(row) for row in rows])
	workflow.remove = lambda row: workflow.transitions.remove(row)
	return workflow


def old_one_level_rows():
	"""The company route as installed before: approve or reject straight from Open."""
	rows = []
	for role in ("Leave Approver", "HR Manager", "System Manager"):
		condition = f"not {OUTLET}" + (" and doc.leave_approver == frappe.session.user" if role == "Leave Approver" else "")
		rows.append(dict(state="Open", action="Approve", next_state="Approved", allowed=role, condition=f"{condition} and {COMPANY_NOT_SELF}"))
		rows.append(dict(state="Open", action="Reject", next_state="Rejected", allowed=role, condition=condition))
	return rows


class TestOneLevelRouteIsRetired(unittest.TestCase):
	"""Every non-outlet leave now reaches HRD: nothing may approve it straight from Open."""

	def test_every_approve_from_open_and_the_leave_approver_reject_are_removed(self):
		workflow = installed(old_one_level_rows())
		with patch("builtins.print") as say:
			self.assertEqual(patch_module.retire_one_level(workflow), 4)
		self.assertEqual({(row.action, row.allowed) for row in workflow.transitions}, {("Reject", "HR Manager"), ("Reject", "System Manager")})
		self.assertIn("removed", " ".join(str(arg) for call in say.call_args_list for arg in call.args))

	def test_outlet_rows_are_never_removed(self):
		outlet = [row for row in configuration()["transitions"] if row["condition"].startswith(OUTLET)]
		workflow = installed(outlet)
		self.assertEqual(patch_module.retire_one_level(workflow), 0)
		self.assertEqual(len(workflow.transitions), len(outlet))


class TestNewDepartmentRows(unittest.TestCase):
	def test_only_non_outlet_rows_are_added_and_outlet_rows_are_never_touched(self):
		rows = patch_module.department_rows(configuration()["transitions"])
		self.assertTrue(rows)
		for row in rows:
			self.assertTrue(row["condition"].startswith(f"not {OUTLET}"), row)
		self.assertEqual({row["state"] for row in rows}, {"Open", "Menunggu Approver 1", "Menunggu Approver 2", "Menunggu HRD"})
		self.assertFalse(any(row["allowed"] in ("PL Outlet", "SPV Outlet") for row in rows))
		self.assertFalse(any(row["state"] == "Open" and row["action"] == "Approve" for row in rows))


class TestOvertimePermissions(unittest.TestCase):
	def test_overtime_approver_copies_the_spv_rights_where_custom_permissions_replaced_the_standard_ones(self):
		template = frappe._dict(name="perm-1", parent="Overtime Request", role="SPV Outlet", permlevel=0, read=1, write=1, create=1, idx=4, owner="x", creation="c", modified="m", modified_by="x")
		inserted = []

		class Doc(frappe._dict):
			def insert(self, **kwargs):
				inserted.append(dict(self))

		with patch("frappe.get_all", side_effect=lambda dt, filters, fields: [template] if filters["parent"] == "Overtime Request" else []), \
			patch("frappe.db.exists", return_value=None), patch("frappe.get_doc", side_effect=lambda values: Doc(values)), patch("frappe.clear_cache"):
			patch_module.add_overtime_permissions()
		self.assertEqual(len(inserted), 1)
		row = inserted[0]
		self.assertEqual((row["doctype"], row["parent"], row["role"], row["read"], row["write"], row["create"]), ("Custom DocPerm", "Overtime Request", "Overtime Approver", 1, 1, 1))
		self.assertFalse({"name", "idx", "creation", "modified", "owner", "modified_by"} & set(row))

	def test_existing_rows_are_not_duplicated(self):
		with patch("frappe.get_all", return_value=[frappe._dict(role="SPV Outlet")]), patch("frappe.db.exists", return_value="perm-9"), \
			patch("frappe.get_doc", side_effect=AssertionError("no insert")):
			patch_module.add_overtime_permissions()


class TestEarlierPatchesKeepPickingOutletRows(unittest.TestCase):
	"""Open now has an outlet and a department 'Ajukan ke HRD'; a site still running the old HRD-route patch must get the outlet one."""

	def test_hrd_route_patch_adds_the_outlet_row(self):
		from custom_hr.patches import add_leave_workflow_hrd_route as hrd_route

		appended = []
		workflow = frappe._dict(transitions=[], append=lambda field, row: appended.append(row), save=lambda: None)
		with patch("frappe.db.exists", return_value=True), patch("frappe.get_doc", return_value=workflow):
			hrd_route.execute()
		self.assertEqual(len(appended), 1)
		self.assertTrue(appended[0]["condition"].startswith(OUTLET), appended[0]["condition"])


def move(leave, stages):
	"""Run move_open_leaves on one Open non-outlet leave whose stage approvers are `stages`."""
	written, shared = {}, []
	with patch("frappe.get_all", return_value=[leave]), \
		patch(f"{patch_module.__name__}.stage_approvers", return_value=stages), \
		patch("frappe.db.get_value", side_effect=lambda dt, name, field=None, *a, **k: {"outlet": None, "user_id": leave.get("user")}[field]), \
		patch("frappe.db.set_value", side_effect=lambda dt, name, values, **k: written.update(values)), \
		patch("frappe.utils.get_fullname", return_value="Budi"), \
		patch("frappe.share.add_docshare", side_effect=lambda dt, name, user, **k: shared.append(user)):
		patch_module.move_open_leaves()
	return written, shared


class TestOpenLeavesMoveOn(unittest.TestCase):
	"""Open non-outlet drafts lose their one-level route: the patch moves them on, as the first install did."""

	def test_moves_to_stage_1_and_shares_it(self):
		written, shared = move(frappe._dict(name="LA-1", employee="E1", user="employee@example.com"), ["a1@example.com", "a2@example.com"])
		self.assertEqual((written["leave_workflow_state"], written["leave_approver"]), ("Menunggu Approver 1", "a1@example.com"))
		self.assertEqual(shared, ["a1@example.com"])

	def test_stage_1_own_leave_goes_to_stage_2_or_hrd(self):
		written, _ = move(frappe._dict(name="LA-2", employee="E1", user="a1@example.com"), ["a1@example.com", "a2@example.com"])
		self.assertEqual((written["leave_workflow_state"], written["leave_approver"]), ("Menunggu Approver 2", "a2@example.com"))
		written, shared = move(frappe._dict(name="LA-3", employee="E1", user="a1@example.com"), ["a1@example.com"])
		self.assertEqual((written, shared), ({"leave_workflow_state": "Menunggu HRD"}, []))

	def test_spv_own_open_leave_goes_to_hrd(self):
		written, shared = move(frappe._dict(name="LA-5", employee="E1", user="a2@example.com"), ["a1@example.com", "a2@example.com"])
		self.assertEqual((written, shared), ({"leave_workflow_state": "Menunggu HRD"}, []))

	def test_without_any_approver_an_open_leave_goes_to_hrd(self):
		written, shared = move(frappe._dict(name="LA-4", employee="E1", user="employee@example.com"), [])
		self.assertEqual((written, shared), ({"leave_workflow_state": "Menunggu HRD"}, []))


class TestThePatchSaysWhatItCouldNotDo(unittest.TestCase):
	def test_tiered_departments_and_their_problems_are_listed(self):
		approvers = {"Finance": ["a1@example.com", "a2@example.com", "a3@example.com"], "IT": ["b1@example.com"]}
		with patch("frappe.get_all", return_value=list(approvers)), \
			patch(f"{patch_module.__name__}.department_approvers", side_effect=lambda name, limit=None: approvers[name]), \
			patch("frappe.get_roles", side_effect=lambda user: ["Leave Approver"]), patch("builtins.print") as say:
			patch_module.report_tiered_departments()
		text = " ".join(str(arg) for call in say.call_args_list for arg in call.args)
		for expected in ("Finance", "IT", "lebih dari 2", "Overtime Approver"):
			self.assertIn(expected, text)
