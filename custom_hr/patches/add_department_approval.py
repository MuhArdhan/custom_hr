"""Tiered approval for non-outlet employees (the Department's Leave & Overtime Approvers) on an installed site.

Leave: adds the Menunggu Approver 1/2 stages and their transitions to the installed Workflow and retires the
one-level route (approve straight from Open): every non-outlet leave now ends at HRD, with the Department's
rows, else the Employee's Leave Approver, as stage 1. Outlet transitions are not touched.
Open non-outlet drafts move on to their first stage, as the first install did for outlets.
The departments that now approve in stages are printed with what to check.
Overtime: its Workflow comes from fixtures. Where the Role Permission Manager replaced the standard
permissions (Custom DocPerm), Overtime Approver gets the same rights as SPV Outlet.
"""

import frappe

from custom_hr.patches.add_approval_override import add_transitions
from custom_hr.patches.setup_native_leave_workflow import (
	NAME, OUTLET, PENDING_APPROVER_1, PENDING_APPROVER_2, STATE_FIELD, configuration,
)
from custom_hr.services.department_approvers import APPROVER_ROLES, MAX_APPROVERS, department_approvers, stage_approvers

NEW_STATES = (PENDING_APPROVER_1, PENDING_APPROVER_2)
NON_OUTLET = f"not {OUTLET}"
OVERTIME_DOCTYPES = ("Overtime Request", "Overtime List")
ROLE, TEMPLATE_ROLE = "Overtime Approver", "SPV Outlet"
NOT_COPIED = ("name", "idx", "creation", "modified", "owner", "modified_by")


def retire_one_level(workflow):
	"""Drop every Approve straight from Open and the Leave Approver's Reject there; returns how many rows went.

	Only non-outlet rows qualify (their condition opens with 'not outlet'); HR's Reject from Open stays.
	"""
	retired = [
		row for row in workflow.transitions
		if row.state == "Open" and (row.condition or "").startswith(NON_OUTLET)
		and (row.action == "Approve" or (row.action == "Reject" and row.allowed == "Leave Approver"))
	]
	for row in retired:
		print(f"{NAME}: removed Open -> {row.action} ({row.allowed}); non-outlet leave now always reaches HRD")
		workflow.remove(row)
	return len(retired)


def department_rows(transitions):
	"""The non-outlet stages, their overrides, HRD's decision and HR's Reject from Open: rows an old Workflow lacks."""
	return [row for row in transitions if row["condition"].startswith(NON_OUTLET)]


def add_leave_stages():
	config = configuration()
	for state in NEW_STATES:
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc(dict(doctype="Workflow State", workflow_state_name=state)).insert()
	for action in {row["action"] for row in config["transitions"]}:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc(dict(doctype="Workflow Action Master", workflow_action_name=action)).insert()
	workflow = frappe.get_doc("Workflow", NAME)
	present = {row.state for row in workflow.states}
	missing = [row for row in config["states"] if row["state"] in NEW_STATES and row["state"] not in present]
	for row in missing:
		workflow.append("states", row)
	if retire_one_level(workflow) or missing:
		workflow.save(ignore_permissions=True)
	add_transitions(NAME, department_rows(config["transitions"]))


def move_open_leaves():
	"""Open non-outlet drafts: the 'Ajukan' routing, recorded without the owner's click."""
	for leave in frappe.get_all("Leave Application", filters={"docstatus": 0, STATE_FIELD: "Open"}, fields=["name", "employee"]):
		if frappe.db.get_value("Employee", leave.employee, "outlet"):
			continue
		rows = stage_approvers(leave.employee)
		user = frappe.db.get_value("Employee", leave.employee, "user_id")
		second = rows[1] if len(rows) > 1 and rows[1] not in (rows[0], user) else None
		own_spv = len(rows) > 1 and rows[1] == user  # the SPV's own leave skips the lower-ranked Leader
		if rows and rows[0] != user and not own_spv:
			state, approver = PENDING_APPROVER_1, rows[0]
		else:
			state, approver = (PENDING_APPROVER_2, second) if second else ("Menunggu HRD", None)
		values = {STATE_FIELD: state}
		if approver:
			values.update(leave_approver=approver, leave_approver_name=frappe.utils.get_fullname(approver))
		frappe.db.set_value("Leave Application", leave.name, values, update_modified=False)
		if approver:
			frappe.share.add_docshare("Leave Application", leave.name, approver, submit=1, flags={"ignore_share_permission": True})


def report_tiered_departments():
	"""Print every Department that now approves in stages, and what would leave its requests stuck."""
	departments = frappe.get_all("Department Approver", filters={"parenttype": "Department", "parentfield": "leave_approvers"}, pluck="parent")
	for name in sorted(set(departments)):
		rows = department_approvers(name, limit=None)
		problems = [f"lebih dari {MAX_APPROVERS} baris, hanya baris 1-{MAX_APPROVERS} yang dipakai"] if len(rows) > MAX_APPROVERS else []
		for user in rows[:MAX_APPROVERS]:
			missing = [role for role in APPROVER_ROLES if role not in frappe.get_roles(user)]
			if missing:
				problems.append(f"{user} belum punya role {', '.join(missing)}")
		print(f"Department {name}: approval bertingkat aktif ({' -> '.join(rows[:MAX_APPROVERS])} -> HRD)"
			+ (f"; PERIKSA: {'; '.join(problems)}" if problems else ""))


def add_overtime_permissions():
	for doctype in OVERTIME_DOCTYPES:
		templates = frappe.get_all("Custom DocPerm", filters={"parent": doctype, "role": TEMPLATE_ROLE, "permlevel": 0}, fields=["*"])
		if not templates or frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": ROLE}):
			continue
		values = {key: value for key, value in templates[0].items() if key not in NOT_COPIED}
		frappe.get_doc({**values, "doctype": "Custom DocPerm", "role": ROLE}).insert(ignore_permissions=True)
		frappe.clear_cache(doctype=doctype)


def execute():
	if frappe.db.exists("Workflow", NAME):
		add_leave_stages()
		move_open_leaves()
		frappe.clear_cache(doctype="Leave Application")
	report_tiered_departments()
	add_overtime_permissions()
