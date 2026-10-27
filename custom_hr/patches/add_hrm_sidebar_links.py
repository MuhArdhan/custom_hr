"""Link Outlet, Attendance and the contract/payroll settings from the HRM sidebar.

Existing rows and any link an administrator already added are left alone.
"""

import frappe

# (label, link_type, link_to, icon, place after the row linking to ...; None = end)
LINKS = [
	("Attendance", "DocType", "Attendance", "clipboard-check", "employee-attendance-gallery"),
	("Grooming Gallery", "Page", "grooming-gallery", "image", "employee-attendance-gallery"),
	("Grooming", "DocType", "Grooming Check", "camera", "Attendance"),
	("Outlet", "DocType", "Outlet", "store", "outlet-roster"),
	("Contract Notification Settings", "DocType", "Contract Notification Settings", "bell", None),
	("Contract Notification Log", "DocType", "Contract Notification Log", "file-text", None),
	("HRM Payroll Settings", "DocType", "HRM Payroll Settings", "settings", None),
]


def add_links(doc):
	changed = False
	for label, link_type, link_to, icon, after in LINKS:
		rows = doc.items
		if any(row.link_type == link_type and row.link_to == link_to for row in rows):
			continue
		row = doc.append("items", dict(type="Link", label=label, link_type=link_type, link_to=link_to, icon=icon, child=0, indent=0))
		rows.remove(row)
		rows.insert(next((i + 1 for i, r in enumerate(rows) if after and r.link_to == after), len(rows)), row)
		changed = True
	for index, item in enumerate(doc.items, 1):
		item.idx = index
	return changed


def execute():
	if not frappe.db.exists("Workspace Sidebar", "HRM"):
		return
	doc = frappe.get_doc("Workspace Sidebar", "HRM")
	if add_links(doc):
		doc.save(ignore_permissions=True)
