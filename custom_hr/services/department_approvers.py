"""Tiered approval for non-outlet employees: the Department's Leave & Overtime Approvers table.

Row 1 and row 2 play the Outlet's Approver 1 and Approver 2 for both leave and overtime;
the leave Workflow reads the same rows by idx (setup_native_leave_workflow.APPROVER_1/2).
"""

import frappe
from frappe import _

MAX_APPROVERS = 2
APPROVER_ROLES = ("Leave Approver", "Overtime Approver")


def department_approvers(department, limit=MAX_APPROVERS):
	"""Approver users of rows 1 and 2 (by idx, as the Workflow reads them), in order; limit=None gives every row."""
	if not department:
		return []
	filters = {"parent": department, "parenttype": "Department", "parentfield": "leave_approvers"}
	if limit:
		filters["idx"] = ["in", list(range(1, limit + 1))]
	return frappe.get_all("Department Approver", filters=filters, order_by="idx", pluck="approver", limit=limit, ignore_permissions=True)


def stage_approvers(employee):
	"""Leave stages of a non-outlet employee: the Department's rows, else the Employee's own Leave Approver."""
	department, leave_approver = frappe.db.get_value("Employee", employee, ["department", "leave_approver"])
	return department_approvers(department) or ([leave_approver] if leave_approver else [])


def validate_department_approvers(doc, method=None):
	"""Department validate: two stages at most, each approver able to act on leave and overtime."""
	rows = [row for row in doc.get("leave_approvers") or [] if row.approver]
	if len(rows) > MAX_APPROVERS:
		frappe.throw(_("Leave & Overtime Approvers berisi maksimal {0} baris: baris 1 adalah approver tahap 1, baris 2 approver tahap 2.").format(MAX_APPROVERS))
	if len({row.approver for row in rows}) < len(rows):
		frappe.throw(_("Satu approver tidak boleh tercantum lebih dari sekali di Leave & Overtime Approvers."))
	for row in rows:
		missing = [role for role in APPROVER_ROLES if role not in frappe.get_roles(row.approver)]
		if missing:
			frappe.throw(_("{0} belum punya role {1}. Tambahkan role tersebut agar pengajuan tidak tertahan di tahapnya.").format(row.approver, ", ".join(missing)))
