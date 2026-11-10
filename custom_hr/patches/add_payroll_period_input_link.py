"""Group Additional Salary and the Input Additional Salary page in one section of the native Payroll sidebar."""

import frappe

from custom_hr.patches.add_hrm_sidebar_links import add_links

PAGE = "payroll-period-input"
ANCHOR = "Additional Salary"
LABEL = "Input Additional Salary"
LINK = [(LABEL, "Page", PAGE, "table", ANCHOR)]
SECTION = {"type": "Section Break", "label": ANCHOR, "icon": "piggy-bank", "indent": 1, "collapsible": 1, "keep_closed": 0}
PAGE_ROW = {"type": "Link", "label": LABEL, "link_type": "Page", "link_to": PAGE, "icon": "table"}


def execute():
	try:
		from frappe.desk.doctype.custom_sidebar.custom_sidebar import (
			SITE_LAYER,
			add_site_sidebar_item,
			base_items,
			get_customization,
		)
		from frappe.desk.doctype.sidebar.sidebar import LINKED_IDENTITY_FIELDS
	except ImportError:  # Frappe before the module sidebars still renders Workspace Sidebar
		return add_to_workspace_sidebar()

	existing = get_customization("Payroll", None)
	doc = (
		frappe.get_doc("Custom Sidebar", existing.name)
		if existing
		else frappe.new_doc("Custom Sidebar").update({"module": "Payroll", "user": SITE_LAYER})
	)
	rows = arrangement(base_items("Payroll"), LINKED_IDENTITY_FIELDS)
	if not rows or not all(is_ours(row) for row in doc.sidebar_items):
		# the site arranged Payroll itself: keep its order and only make sure the page is reachable
		return add_site_sidebar_item("Payroll", PAGE_ROW)
	doc.set("sidebar_items", [])
	for row in rows:
		doc.append("sidebar_items", row)
	doc.save(ignore_permissions=True)


def arrangement(base, identity_fields) -> list[dict]:
	"""Base rows down to the anchor, then a section holding the anchor and the page; [] when the anchor is missing."""
	lead = []
	for item in base:
		reference = {**{field: item.get(field) for field in identity_fields}, "child": 0}
		if item.get("link_to") == ANCHOR:
			return [*lead, {**SECTION, "added": 1, "child": 0}, {**reference, "child": 1}, {**PAGE_ROW, "added": 1, "child": 1}]
		lead.append({**reference, "child": item.get("child") or 0})
	return []


def is_ours(row) -> bool:
	"""Rows this patch writes: plain references, the section and the page. Anything else is the site's own choice."""
	if row.get("link_to") == PAGE or (row.get("type") == "Section Break" and row.get("label") == ANCHOR):
		return True
	return not (row.get("added") or row.get("hidden") or row.get("label") or row.get("icon"))


def add_to_workspace_sidebar():
	if not frappe.db.exists("Workspace Sidebar", "Payroll"):
		return
	doc = frappe.get_doc("Workspace Sidebar", "Payroll")
	if add_links(doc, LINK):
		doc.flags.ignore_links = True  # a row left by another app's removed DocType must not block this link
		doc.save(ignore_permissions=True)
