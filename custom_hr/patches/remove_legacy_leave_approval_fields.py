"""Remove only the retired custom approval fields, never native Workflow fields."""

import frappe

LEGACY_FIELDS = {
	"outlet_leave_section": "Section Break",
	"outlet_leave_outlet": "Link",
	"outlet_leave_pl": "Link",
	"outlet_leave_stage": "Select",
	"outlet_leave_pl_by": "Link",
	"outlet_leave_pl_on": "Datetime",
	"outlet_leave_decision_by": "Link",
	"outlet_leave_decision_on": "Datetime",
}


def execute():
	for name in frappe.get_all("Workflow", filters={"document_type": "Leave Application"}, pluck="name"):
		workflow = frappe.get_doc("Workflow", name)
		if workflow.workflow_state_field in LEGACY_FIELDS or any(row.update_field in LEGACY_FIELDS for row in workflow.states) or any(any(field in (row.condition or "") for field in LEGACY_FIELDS) for row in workflow.transitions):
			frappe.throw("Review Workflow references before removing retired fields: " + name)
	fields = frappe.get_all("Custom Field",
		filters={"dt": "Leave Application", "fieldname": ["in", list(LEGACY_FIELDS)]},
		fields=["name", "fieldname", "module", "fieldtype"])
	for field in fields:
		if field.module != "HRM" or field.fieldtype != LEGACY_FIELDS[field.fieldname]:
			frappe.throw("Retired field has an unexpected customization; review first: " + field.name)
	for field in fields:
		# Native deletion also removes that field's property setters/layout entries.
		frappe.delete_doc("Custom Field", field.name, ignore_permissions=True)
	columns = set(frappe.db.get_table_columns("Leave Application")) & LEGACY_FIELDS.keys()
	if columns:
		# Names are from the fixed allowlist above, never user input. Only old,
		# unused columns are dropped; no leave document is saved or submitted.
		frappe.db.sql_ddl("ALTER TABLE `tabLeave Application` " + ", ".join(
			f"DROP COLUMN `{field}`" for field in sorted(columns)))
		frappe.client_cache.delete_value("table_columns::tabLeave Application")
	frappe.clear_cache(doctype="Leave Application")
