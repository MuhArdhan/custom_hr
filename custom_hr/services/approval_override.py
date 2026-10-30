"""A user holding every approver role of a workflow can step in when one stage is stuck.

Such a user (usually the admin account) approves or rejects on behalf of the absent
approver; approving only moves the request to the next stage, never straight to final.
Users with just one of the roles still act only at their own stage.
"""

OVERTIME_ROLES = ("Outlet Leader", "SPV Outlet", "HR Manager")
LEAVE_ROLES = ("PL Outlet", "HR Manager")
SPV_LEAVE_ROLES = ("SPV Outlet", "HR Manager")
OVERRIDE_ROLE = "HR Manager"  # the transition's role; the condition demands the rest


def holds_roles(*roles):
	"""Workflow condition: the session user has all roles. Administrator has every role but no Has Role rows."""
	checks = " and ".join(
		f'frappe.db.get_value("Has Role", {{"parent": frappe.session.user, "parenttype": "User", "role": "{role}"}})'
		for role in roles
	)
	return f'(frappe.session.user == "Administrator" or ({checks}))'


def overtime_transitions():
	"""Override steps for the stuck Leader and SPV stages; HR Manager already decides at Menunggu HRD."""
	who = holds_roles(*OVERTIME_ROLES)
	not_leader = "doc.approver_1 != frappe.session.user"  # the recorded leader uses the normal step
	not_spv = "doc.approver_2 != frappe.session.user"
	steps = [
		("Menunggu Leader", "Setujui", "Menunggu SPV", f"{who} and {not_leader} and doc.approver_2"),
		("Menunggu Leader", "Setujui", "Menunggu HRD", f"{who} and {not_leader} and not doc.approver_2"),
		("Menunggu Leader", "Tolak", "Ditolak", f"{who} and {not_leader}"),
		("Menunggu SPV", "Setujui", "Menunggu HRD", f"{who} and {not_spv}"),
		("Menunggu SPV", "Tolak", "Ditolak", f"{who} and {not_spv}"),
	]
	return [
		dict(state=state, action=action, next_state=target, allowed=OVERRIDE_ROLE, condition=condition, allow_self_approval=0)
		for state, action, target, condition in steps
	]


def leave_transitions():
	"""Override steps for a stuck Menunggu PL / Menunggu SPV stage; never for the user's own leave."""
	from custom_hr.patches.setup_native_leave_workflow import NEEDS_SPV, SKIP_SPV

	outlet = 'frappe.db.get_value("Employee", doc.employee, "outlet")'
	not_self = 'doc.owner != frappe.session.user and frappe.db.get_value("Employee", doc.employee, "user_id") != frappe.session.user'
	override = f"{outlet} and {holds_roles(*LEAVE_ROLES)} and doc.leave_approver != frappe.session.user"
	spv_override = f"{outlet} and {holds_roles(*SPV_LEAVE_ROLES)} and doc.leave_approver != frappe.session.user"
	return [
		dict(state="Menunggu PL", action="Approve", next_state="Menunggu SPV", allowed=OVERRIDE_ROLE, condition=f"{override} and {not_self} and {NEEDS_SPV}", allow_self_approval=0),
		dict(state="Menunggu PL", action="Approve", next_state="Menunggu HRD", allowed=OVERRIDE_ROLE, condition=f"{override} and {not_self} and {SKIP_SPV}", allow_self_approval=0),
		dict(state="Menunggu PL", action="Reject", next_state="Rejected", allowed=OVERRIDE_ROLE, condition=override, allow_self_approval=1),
		dict(state="Menunggu SPV", action="Approve", next_state="Menunggu HRD", allowed=OVERRIDE_ROLE, condition=f"{spv_override} and {not_self}", allow_self_approval=0),
		dict(state="Menunggu SPV", action="Reject", next_state="Rejected", allowed=OVERRIDE_ROLE, condition=spv_override, allow_self_approval=1),
	]
