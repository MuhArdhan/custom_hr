"""HRM Payroll Settings moved into the HRM tab of the native Payroll Settings: its values, rows and links follow.

Plain SQL: this runs before fixtures make the custom fields, and a single's values and its table rows do not
need them to exist. Values already set on Payroll Settings are kept.
"""

import frappe

OLD, NEW = "HRM Payroll Settings", "Payroll Settings"
CHILDREN = (
	"HRM Wage Component",
	"HRM Daily Rate",
	"HRM BPJS Rate",
	"HRM Attendance Penalty Rate",
	"HRM Shift Allowance",
	"HRM Payroll Match Column",
)
OWN = ("name", "creation", "modified", "modified_by", "owner", "docstatus", "idx")
# (child table of the desk page, its parent doctype)
LINKS = (("Workspace Link", "Workspace"), ("Workspace Shortcut", "Workspace"), ("Workspace Sidebar Item", "Workspace Sidebar"))


def execute():
	frappe.db.sql(
		"""UPDATE `tabSingles` SET doctype = %(new)s
		WHERE doctype = %(old)s AND field NOT IN %(own)s
		AND field NOT IN (SELECT field FROM (SELECT field FROM `tabSingles` WHERE doctype = %(new)s) AS kept)""",
		{"old": OLD, "new": NEW, "own": OWN},
	)
	for child in CHILDREN:
		if frappe.db.table_exists(child):
			frappe.db.sql(f"UPDATE `tab{child}` SET parent = %s, parenttype = %s WHERE parenttype = %s", (NEW, NEW, OLD))
	for table, parent_doctype in LINKS:
		if not frappe.db.table_exists(table):
			continue
		for row in frappe.get_all(table, filters={"link_to": OLD, "parenttype": parent_doctype}, fields=["name", "parent"]):
			if frappe.db.exists(table, {"parent": row.parent, "link_to": NEW}):
				frappe.db.delete(table, {"name": row.name})  # the page already links the native settings
			else:
				frappe.db.set_value(table, row.name, {"link_to": NEW, "label": NEW}, update_modified=False)
	for name, content in frappe.get_all("Workspace", filters={"content": ["like", f"%{OLD}%"]}, fields=["name", "content"], as_list=True):
		content = content.replace(f'"shortcut_name":"{OLD}"', f'"shortcut_name":"{NEW}"')
		frappe.db.set_value("Workspace", name, "content", content, update_modified=False)
	frappe.delete_doc("DocType", OLD, force=True, ignore_missing=True)
	frappe.db.delete("Singles", {"doctype": OLD})  # its own name/modified rows: delete_doc leaves them
	frappe.clear_cache()
