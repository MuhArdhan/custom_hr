"""Add Grooming Kuku Gallery after Grooming Gallery in the HRM sidebar if not already present."""

import frappe


def _insert_after(doctype: str, name: str):
	if not frappe.db.table_exists(doctype) or not frappe.db.exists(doctype, name):
		return
	doc = frappe.get_doc(doctype, name)
	rows = doc.items
	if any(row.link_type == "Page" and row.link_to == "grooming-kuku-gallery" for row in rows):
		return
	row = doc.append(
		"items",
		dict(type="Link", label="Grooming Kuku Gallery", link_type="Page", link_to="grooming-kuku-gallery", icon="", child=1, indent=0),
	)
	rows.remove(row)
	anchor = next((i + 1 for i, r in enumerate(rows) if r.link_to == "grooming-gallery"), len(rows))
	rows.insert(anchor, row)
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
	_insert_after("Sidebar", "HRM")
	_insert_after("Workspace Sidebar", "HRM")
