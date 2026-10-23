"""Add Leave Calendar beside Leave Application without replacing sidebar layouts."""

import frappe


def insert_calendar(doc, table_field):
	rows = doc.get(table_field) or []
	if any(row.link_type == "Page" and row.link_to == "leave-calendar" for row in rows):
		return False
	position = next((i for i, row in enumerate(rows) if row.link_type == "DocType" and row.link_to == "Leave Application"), len(rows))
	row = doc.append(table_field, dict(type="Link", label="Leave Calendar",
		link_type="Page", link_to="leave-calendar", icon="calendar-days",
		child=0, indent=0, open_in_new_tab=1))
	rows = doc.get(table_field)
	rows.remove(row)
	rows.insert(position, row)
	for index, item in enumerate(rows, 1):
		item.idx = index
	return True


def execute():
	if not frappe.db.exists("Page", "leave-calendar"):
		return
	previous_developer_mode = frappe.conf.developer_mode
	try:
		# Save native configuration without exporting the upstream HRMS app.
		frappe.conf.developer_mode = 0
		for doctype, table_field in [("Workspace", "sidebar_items"), ("Workspace Sidebar", "items")]:
			if not frappe.db.exists("DocType", doctype) or not frappe.db.exists(doctype, "Leaves"):
				continue
			doc = frappe.get_doc(doctype, "Leaves")
			if doc.meta.has_field(table_field) and insert_calendar(doc, table_field):
				doc.save(ignore_permissions=True)
	finally:
		frappe.conf.developer_mode = previous_developer_mode
