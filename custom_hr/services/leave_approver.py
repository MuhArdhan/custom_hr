"""Leave Approver for outlet employees comes from the Outlet (Approver 1)."""

import frappe
from frappe.model.workflow import apply_workflow, get_transitions
from hrms.api import get_leave_approval_details as hrms_get_leave_approval_details
from hrms.hr.doctype.leave_application.leave_application import get_employee_leave_approver

PENDING_PL = "Menunggu PL"
SUBMIT_ACTIONS = ("Ajukan ke PL", "Ajukan ke HRD")


@frappe.whitelist()
def get_leave_approver(employee, leave_application=None):
	"""HRMS lookup (Employee, then Department), falling back to the Outlet's Approver 1."""
	approver = get_employee_leave_approver(employee)
	if approver:
		return approver
	outlet = frappe.db.get_value("Employee", employee, "outlet")
	return outlet and frappe.db.get_value("Outlet", outlet, "approver_1")


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


def stage_label(state, doc):
	"""Name the approver instead of the generic 'Menunggu PL'."""
	name = doc.get("leave_approver_name") or doc.get("leave_approver")
	return f"Menunggu {name}" if state == PENDING_PL and name else state
