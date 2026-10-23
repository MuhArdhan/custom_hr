"""Add the direct-to-HRD submission route to an already installed leave Workflow.

setup_native_leave_workflow never overwrites an installed Workflow, so this
patch adds only the new transition and tightens "Ajukan ke PL". A condition
the administrator already edited is left untouched.
"""

import frappe

from custom_hr.patches.setup_native_leave_workflow import NAME, configuration

PL_ACTION = "Ajukan ke PL"
HRD_ACTION = "Ajukan ke HRD"


def execute():
	if not frappe.db.exists("Workflow", NAME):
		return
	wanted = {
		row["action"]: row
		for row in configuration()["transitions"]
		if row["state"] == "Open" and row["action"] in (PL_ACTION, HRD_ACTION)
	}
	# The previous condition is the new one without its trailing employee-is-PL check.
	previous_pl_condition = wanted[PL_ACTION]["condition"].rsplit(" and ", 1)[0]

	workflow = frappe.get_doc("Workflow", NAME)
	changed = False
	for row in workflow.transitions:
		if row.state == "Open" and row.action == PL_ACTION and row.condition == previous_pl_condition:
			row.condition = wanted[PL_ACTION]["condition"]
			changed = True
	if not any(row.state == "Open" and row.action == HRD_ACTION for row in workflow.transitions):
		if not frappe.db.exists("Workflow Action Master", HRD_ACTION):
			frappe.get_doc(dict(doctype="Workflow Action Master", workflow_action_name=HRD_ACTION)).insert()
		workflow.append("transitions", wanted[HRD_ACTION])
		changed = True
	if changed:
		workflow.save()
