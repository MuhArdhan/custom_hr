"""Add Grooming Settings under Setup in the HRM sidebar if not already present."""

import frappe


def _append_link(doctype: str, name: str):
	if not frappe.db.table_exists(doctype) or not frappe.db.exists(doctype, name):
		return
	doc = frappe.get_doc(doctype, name)
	rows = doc.items
	if any(row.link_type == "DocType" and row.link_to == "Grooming Settings" for row in rows):
		return
	in_setup = any(row.type == "Section Break" and row.label == "Setup" for row in rows)
	doc.append(
		"items",
		dict(type="Link", label="Grooming Settings", link_type="DocType", link_to="Grooming Settings", icon="sliders", child=int(in_setup), indent=0),
	)
	for index, item in enumerate(doc.items, 1):
		item.idx = index
	previous_developer_mode = frappe.conf.developer_mode
	try:
		frappe.conf.developer_mode = 0
		doc.flags.ignore_links = True
		doc.save(ignore_permissions=True)
	finally:
		frappe.conf.developer_mode = previous_developer_mode


def execute():
	_append_link("Sidebar", "HRM")
	_append_link("Workspace Sidebar", "HRM")
