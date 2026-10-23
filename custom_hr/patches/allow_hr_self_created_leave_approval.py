"""Let HR approve a leave request it created for someone else, on an installed Workflow.

setup_native_leave_workflow never overwrites an installed Workflow, so this
patch updates only the HR Approve transitions. A transition whose condition
the administrator already edited is left untouched.
"""

import frappe

from custom_hr.patches.setup_native_leave_workflow import NAME, configuration


def execute():
	if not frappe.db.exists("Workflow", NAME):
		return
	wanted = [row for row in configuration()["transitions"] if row["action"] == "Approve"]
	hrd = next(row for row in wanted if row["state"] == "Menunggu HRD")
	# The previous condition also required doc.owner != session user.
	prefix, employee_check = hrd["condition"].rsplit(" and ", 1)
	previous_hrd_condition = f"{prefix} and doc.owner != frappe.session.user and {employee_check}"

	workflow = frappe.get_doc("Workflow", NAME)
	changed = False
	for row in workflow.transitions:
		if row.action != "Approve":
			continue
		if row.state == "Menunggu HRD" and row.allowed == "HR Manager" and row.condition == previous_hrd_condition:
			row.condition = hrd["condition"]
			row.allow_self_approval = 1
			changed = True
		elif row.state == "Open" and row.allowed in ("HR Manager", "System Manager") and not row.allow_self_approval:
			row.allow_self_approval = 1
			changed = True
	if changed:
		workflow.save()
