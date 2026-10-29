"""Let a user holding every approver role step in at a stuck leave or overtime stage.

Only the override transitions are added; the installed workflows are otherwise left as edited.
"""

import frappe

from custom_hr.patches.setup_native_leave_workflow import NAME as LEAVE_WORKFLOW
from custom_hr.services.approval_override import leave_transitions, overtime_transitions


def add_transitions(workflow_name, transitions):
	workflow = frappe.get_doc("Workflow", workflow_name)
	key = lambda row: (row.get("state"), row.get("action"), row.get("next_state"), row.get("allowed"), row.get("condition") or "")
	existing = {key(row) for row in workflow.transitions}
	missing = [row for row in transitions if key(row) not in existing]
	for row in missing:
		workflow.append("transitions", row)
	if missing:
		workflow.save(ignore_permissions=True)


def execute():
	if frappe.db.exists("Workflow", LEAVE_WORKFLOW):
		add_transitions(LEAVE_WORKFLOW, leave_transitions())
	overtime = frappe.db.get_value("Workflow", {"document_type": "Overtime Request"}, "name")
	if overtime:
		add_transitions(overtime, overtime_transitions())
