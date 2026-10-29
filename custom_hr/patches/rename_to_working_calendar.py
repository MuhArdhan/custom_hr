"""Show the leave-calendar page as "Working Calendar" now that it holds overtime too.

Only labels change: the page route stays leave-calendar, so links and bookmarks keep working.
"""

import frappe

OLD_LABEL = "Leave Calendar"
NEW_LABEL = "Working Calendar"
PAGE = "leave-calendar"


def execute():
	if not frappe.db.exists("Page", PAGE):
		return
	frappe.db.set_value("Page", PAGE, "title", NEW_LABEL, update_modified=False)
	previous_developer_mode = frappe.conf.developer_mode
	try:
		# Save native configuration without exporting the upstream HRMS app.
		frappe.conf.developer_mode = 0
		for name in frappe.get_all("Workspace", filters={"content": ["like", f"%{OLD_LABEL}%"]}, pluck="name"):
			workspace = frappe.get_doc("Workspace", name)
			for shortcut in workspace.shortcuts:
				if shortcut.link_to == PAGE and shortcut.label == OLD_LABEL:
					shortcut.label = NEW_LABEL
			content = frappe.parse_json(workspace.content or "[]")
			for block in content:
				data = block.get("data") or {}
				if block.get("type") == "shortcut" and data.get("shortcut_name") == OLD_LABEL:
					data["shortcut_name"] = NEW_LABEL
			workspace.content = frappe.as_json(content)
			workspace.save(ignore_permissions=True)
		if frappe.db.exists("DocType", "Workspace Sidebar"):
			for name in frappe.get_all("Workspace Sidebar Item", filters={"link_to": PAGE, "label": OLD_LABEL}, pluck="parent", distinct=True):
				sidebar = frappe.get_doc("Workspace Sidebar", name)
				for item in sidebar.items:
					if item.link_to == PAGE and item.label == OLD_LABEL:
						item.label = NEW_LABEL
				sidebar.save(ignore_permissions=True)
	finally:
		frappe.conf.developer_mode = previous_developer_mode
