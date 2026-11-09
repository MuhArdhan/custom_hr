"""Link the Input Payroll Periode page from the native Payroll sidebar, right after Additional Salary."""

import frappe

from custom_hr.patches.add_hrm_sidebar_links import add_links

PAGE = "payroll-period-input"
ANCHOR = "Additional Salary"
LINK = [("Input Payroll Periode", "Page", PAGE, "table", ANCHOR)]


def execute():
	try:
		from frappe.desk.doctype.custom_sidebar.custom_sidebar import add_site_sidebar_item, base_items, get_customization
		from frappe.desk.doctype.sidebar.sidebar import LINKED_IDENTITY_FIELDS, item_key
	except ImportError:  # Frappe before the module sidebars still renders Workspace Sidebar
		return add_to_workspace_sidebar()

	add_site_sidebar_item("Payroll", {"type": "Link", "label": LINK[0][0], "link_type": "Page", "link_to": PAGE, "icon": "table"})
	doc = frappe.get_doc("Custom Sidebar", get_customization("Payroll", None).name)
	base = base_items("Payroll")
	base_keys = {item_key(item) for item in base}
	if any(item_key(row) in base_keys for row in doc.sidebar_items):
		return  # the site arranged Payroll itself; keep its order, the link stays where append put it
	lead = rows_up_to_anchor(base, LINKED_IDENTITY_FIELDS)
	if not lead:
		return
	# a layer of only appends renders at the end; naming the base rows down to the anchor places the link after it
	ours = [row.as_dict(no_default_fields=True) for row in doc.sidebar_items if row.link_to == PAGE]
	rest = [row.as_dict(no_default_fields=True) for row in doc.sidebar_items if row.link_to != PAGE]
	doc.set("sidebar_items", [])
	for row in lead + ours + rest:
		doc.append("sidebar_items", row)
	doc.save(ignore_permissions=True)


def rows_up_to_anchor(base, identity_fields):
	"""Reference rows for the base items from the top down to the anchor, or [] when it is missing."""
	lead = []
	for item in base:
		lead.append({**{field: item.get(field) for field in identity_fields}, "child": item.get("child") or 0})
		if item.get("link_to") == ANCHOR:
			return lead
	return []


def add_to_workspace_sidebar():
	if not frappe.db.exists("Workspace Sidebar", "Payroll"):
		return
	doc = frappe.get_doc("Workspace Sidebar", "Payroll")
	if add_links(doc, LINK):
		doc.flags.ignore_links = True  # a row left by another app's removed DocType must not block this link
		doc.save(ignore_permissions=True)
