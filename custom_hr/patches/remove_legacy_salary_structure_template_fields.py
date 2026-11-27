"""Remove retired Salary Structure template custom fields replaced by lintas_company global scope."""

import frappe

LEGACY_FIELDS = {
	"is_master_template": "Check",
	"template_prefix": "Data",
	"source_template": "Link",
}


def execute():
	fields = frappe.get_all(
		"Custom Field",
		filters={"dt": "Salary Structure", "fieldname": ["in", list(LEGACY_FIELDS)]},
		fields=["name", "fieldname", "module", "fieldtype"],
	)
	for field in fields:
		if field.module != "HRM" or field.fieldtype != LEGACY_FIELDS[field.fieldname]:
			continue
		frappe.delete_doc("Custom Field", field.name, ignore_permissions=True)

	columns = set(frappe.db.get_table_columns("Salary Structure")) & LEGACY_FIELDS.keys()
	if columns:
		frappe.db.sql_ddl(
			"ALTER TABLE `tabSalary Structure` " + ", ".join(f"DROP COLUMN `{col}`" for col in sorted(columns))
		)
		frappe.client_cache.delete_value("table_columns::tabSalary Structure")
	frappe.clear_cache(doctype="Salary Structure")
