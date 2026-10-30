"""Leave Approver for outlet employees comes from the Outlet (Approver 1)."""

import frappe
from frappe.model.workflow import apply_workflow, get_transitions
from hrms.api import get_leave_approval_details as hrms_get_leave_approval_details
from hrms.hr.doctype.leave_application.leave_application import get_employee_leave_approver

PENDING_PL = "Menunggu PL"
PENDING_STAGES = (PENDING_PL, "Menunggu SPV")  # stages that wait for one named approver
SUBMIT_ACTIONS = ("Ajukan ke PL", "Ajukan ke SPV", "Ajukan ke HRD")


@frappe.whitelist()
def get_leave_approver(employee, leave_application=None):
	"""HRMS lookup (Employee, then Department), falling back to the Outlet's Approver 1."""
	approver = get_employee_leave_approver(employee)
	if approver:
		return approver
	outlet = frappe.db.get_value("Employee", employee, "outlet")
	return outlet and (frappe.db.get_value("Outlet", outlet, "approver_1") or frappe.db.get_value("Outlet", outlet, "approver_2"))


@frappe.whitelist()
def get_leave_approval_details(employee):
	"""Same answer for the HRMS mobile app: the Outlet approver is the default and a listed option."""
	details = hrms_get_leave_approval_details(employee)
	if details.get("leave_approver"):
		return details
	approver = get_leave_approver(employee)
	if approver:
		name = frappe.db.get_value("User", approver, "full_name")
		details.update(leave_approver=approver, leave_approver_name=name)
		details["department_approvers"] = [*details["department_approvers"], {"name": approver, "full_name": name}]
	return details


def fill_leave_approver(doc, method=None):
	"""before_validate: a Leave Application created without an approver (HR, API) still gets one."""
	if doc.employee and not doc.leave_approver:
		doc.leave_approver = get_leave_approver(doc.employee)


def submit_to_approver(doc, method=None):
	"""after_insert: take the 'Ajukan' step for the employee. Leaves without one (non-outlet) stay Open."""
	for transition in get_transitions(doc):
		if transition.action in SUBMIT_ACTIONS:
			try:
				apply_workflow(doc, transition.action)
			except (frappe.ValidationError, frappe.PermissionError):
				frappe.clear_messages()  # stays Open; the employee can still press the button
			return


def hand_over_to_approver_2(doc, method=None):
	"""on_update: at Menunggu SPV the outlet's Approver 2 becomes the leave approver.

	Set after the save instead of through the workflow state: native on_update would then
	un-share the request from the PL, which the PL has no permission to do. The PL keeps read access.
	"""
	if doc.get("leave_workflow_state") != "Menunggu SPV":
		return
	outlet = frappe.db.get_value("Employee", doc.employee, "outlet")
	spv = outlet and frappe.db.get_value("Outlet", outlet, "approver_2")
	if not spv or doc.leave_approver == spv:
		return
	doc.db_set({"leave_approver": spv, "leave_approver_name": frappe.utils.get_fullname(spv)})
	frappe.share.add_docshare(doc.doctype, doc.name, spv, submit=1, flags={"ignore_share_permission": True})


def stage_label(state, doc):
	"""Name the approver instead of the generic 'Menunggu PL' / 'Menunggu SPV' state."""
	name = doc.get("leave_approver_name") or doc.get("leave_approver")
	return f"Waiting for {name}" if state in PENDING_STAGES and name else state
