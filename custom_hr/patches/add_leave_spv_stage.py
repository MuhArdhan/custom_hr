"""Add the optional Approver 2 (Menunggu SPV) stage to an already installed leave Workflow.

The routes that used to go straight to HRD only skip the new stage when the outlet has
no Approver 2. A condition the administrator already edited is left untouched.
"""

import frappe

from custom_hr.patches.add_approval_override import add_transitions
from custom_hr.patches.setup_native_leave_workflow import NAME, SKIP_SPV, configuration, grant_status_edit

STAGE = "Menunggu SPV"
SUBMIT_ACTION = "Ajukan ke SPV"
SUFFIX = " and " + SKIP_SPV


def execute():
	if not frappe.db.exists("Workflow", NAME):
		return
	grant_status_edit()
	if not frappe.db.exists("Workflow State", STAGE):
		frappe.get_doc(dict(doctype="Workflow State", workflow_state_name=STAGE)).insert()
	if not frappe.db.exists("Workflow Action Master", SUBMIT_ACTION):
		frappe.get_doc(dict(doctype="Workflow Action Master", workflow_action_name=SUBMIT_ACTION)).insert()

	config = configuration()
	wanted = config["transitions"]  # already includes the override steps
	workflow = frappe.get_doc("Workflow", NAME)
	if not any(row.state == STAGE for row in workflow.states):
		workflow.append("states", next(row for row in config["states"] if row["state"] == STAGE))
	key = lambda row: (row.get("state"), row.get("action"), row.get("next_state"), row.get("allowed"))
	tightened = {key(row): row["condition"] for row in wanted if row["condition"].endswith(SUFFIX)}
	for row in workflow.transitions:
		condition = tightened.get(key(row))
		if condition and row.condition == condition[: -len(SUFFIX)]:
			row.condition = condition
	workflow.save(ignore_permissions=True)
	add_transitions(NAME, [row for row in wanted if STAGE in (row["state"], row["next_state"])])
	frappe.clear_cache(doctype="Leave Application")
