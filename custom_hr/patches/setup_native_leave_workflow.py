"""One-time native Workflow configuration. No custom approval runtime/hooks.

Once installed, administrators edit the Workflow document in Desk. This setup
does not overwrite it on subsequent migrations.
"""

import frappe

NAME = "Approval Cuti dan Izin"
STATE_FIELD = "leave_workflow_state"


def configuration():
	outlet = 'frappe.db.get_value("Employee", doc.employee, "outlet")'
	pl = f'frappe.db.get_value("Outlet", {outlet}, "approver_1")'
	not_self = 'doc.owner != frappe.session.user and frappe.db.get_value("Employee", doc.employee, "user_id") != frappe.session.user'
	states = []
	for name, status, role, update_field, update_value in [
		("Open", "0", "All", "status", "Open"),
		("Menunggu PL", "0", "PL Outlet", "leave_approver", pl),
		("Menunggu HRD", "0", "HR Manager", "status", "Open"),
		("Approved", "1", "HR Manager", "status", "Approved"),
		("Rejected", "1", "HR Manager", "status", "Rejected"),
		("Cancelled", "2", "HR Manager", "status", "Cancelled"),
		("Approved (Draft Lama)", "0", "HR Manager", "status", "Approved"),
		("Rejected (Draft Lama)", "0", "HR Manager", "status", "Rejected"),
	]:
		states.append(dict(state=name, doc_status=status, allow_edit=role,
			update_field=update_field, update_value=update_value,
			evaluate_as_expression=int(name == "Menunggu PL"), send_email=0))
	transitions = []
	def transition(state, action, target, role, condition, self_approval=0):
		transitions.append(dict(state=state, action=action, next_state=target,
			allowed=role, condition=condition, allow_self_approval=self_approval))
	employee_user = 'frappe.db.get_value("Employee", doc.employee, "user_id")'
	transition("Open", "Ajukan ke PL", "Menunggu PL", "All",
		f'{outlet} and {pl} and doc.owner == frappe.session.user and {employee_user} != {pl}', 1)
	# No PL to ask (outlet without one, or the PL's own leave): go straight to HRD.
	transition("Open", "Ajukan ke HRD", "Menunggu HRD", "All",
		f'{outlet} and doc.owner == frappe.session.user and (not {pl} or {employee_user} == {pl})', 1)
	pl_condition = f'{outlet} and doc.leave_approver == frappe.session.user and {pl} == frappe.session.user'
	transition("Menunggu PL", "Approve", "Menunggu HRD", "PL Outlet", f'{pl_condition} and {not_self}')
	transition("Menunggu PL", "Reject", "Rejected", "PL Outlet", pl_condition, 1)
	# HR may approve a request it created for someone else, never its own leave.
	transition("Menunggu HRD", "Approve", "Approved", "HR Manager", f'{outlet} and {employee_user} != frappe.session.user', 1)
	transition("Menunggu HRD", "Reject", "Rejected", "HR Manager", outlet, 1)
	# Company keeps one-level nominated Leave Approver / authorized HR decisions.
	company_not_self = '(not frappe.db.get_value("HR Settings", None, "prevent_self_leave_approval") or frappe.db.get_value("Employee", doc.employee, "user_id") != frappe.session.user)'
	for role in ["Leave Approver", "HR Manager", "System Manager"]:
		condition = f'not {outlet}'
		if role == "Leave Approver":
			condition += ' and doc.leave_approver == frappe.session.user'
		transition("Open", "Approve", "Approved", role, f'{condition} and {company_not_self}', int(role != "Leave Approver"))
		transition("Open", "Reject", "Rejected", role, condition, 1)
	for role in ["HR Manager", "System Manager"]:
		for state in ["Approved", "Rejected"]:
			transition(state, "Cancel", "Cancelled", role, "", 1)
	return dict(doctype="Workflow", workflow_name=NAME, document_type="Leave Application",
		is_active=1, workflow_state_field=STATE_FIELD, send_email_alert=0,
		states=states, transitions=transitions)


def execute():
	if frappe.db.exists("Workflow", NAME):
		return  # Never replace administrator edits.
	active = frappe.db.get_value("Workflow", {"document_type": "Leave Application", "is_active": 1}, "name")
	if active:
		frappe.throw("Review the existing Leave Application workflow first: " + active)
	if not frappe.db.exists("Role", "PL Outlet"):
		frappe.get_doc(dict(doctype="Role", role_name="PL Outlet", desk_access=1)).insert()
	config = configuration()
	for state in config["states"]:
		if not frappe.db.exists("Workflow State", state["state"]):
			frappe.get_doc(dict(doctype="Workflow State", workflow_state_name=state["state"])).insert()
	for action in {t["action"] for t in config["transitions"]}:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc(dict(doctype="Workflow Action Master", workflow_action_name=action)).insert()
	frappe.get_doc(config).insert()
	# Only higher-level status editing is granted to PL. Read/write/submit of
	# individual requests comes from native share_doc_with_approver, not broad HR access.
	from frappe.permissions import setup_custom_perms
	setup_custom_perms("Leave Application")
	if not frappe.db.exists("Custom DocPerm", {"parent": "Leave Application", "role": "PL Outlet", "permlevel": 1}):
		frappe.get_doc(dict(doctype="Custom DocPerm", parent="Leave Application",
			role="PL Outlet", permlevel=1, read=1, write=1)).insert()
	frappe.clear_cache(doctype="Leave Application")
	# Workflow.on_update populates blanks by docstatus. Correct historical state
	# labels without changing status, docstatus, modified or historical effects.
	previous_mute = frappe.flags.mute_emails
	frappe.flags.mute_emails = True
	try:
		for row in frappe.get_all("Leave Application", fields=["name", "docstatus", "status", "employee", "leave_approver"]):
			state = row.status if row.status in {"Approved", "Rejected", "Cancelled"} else "Open"
			if row.docstatus == 0 and row.status in {"Approved", "Rejected"}:
				state += " (Draft Lama)"
			values = {STATE_FIELD: state}
			if row.docstatus == 0 and row.status == "Open":
				outlet = frappe.db.get_value("Employee", row.employee, "outlet")
				if outlet:
					pl = frappe.db.get_value("Outlet", outlet, "approver_1")
					if not pl or "PL Outlet" not in frappe.get_roles(pl):
						frappe.throw("Configure an Approver 1 with PL Outlet role for " + outlet)
					values.update({STATE_FIELD: "Menunggu PL", "leave_approver": pl,
						"leave_approver_name": frappe.utils.get_fullname(pl)})
			frappe.db.set_value("Leave Application", row.name, values, update_modified=False)
			if values[STATE_FIELD] == "Menunggu PL":
				from hrms.hr.utils import share_doc_with_approver
				share_doc_with_approver(frappe.get_doc("Leave Application", row.name), values["leave_approver"])
	finally:
		frappe.flags.mute_emails = previous_mute
	frappe.clear_cache(doctype="Leave Application")
