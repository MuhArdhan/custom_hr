"""Expose the calendar without replacing any existing workspace layout."""

import frappe


def execute():
	if not frappe.db.exists("Workspace", "Shift & Attendance"):
		return
	workspace = frappe.get_doc("Workspace", "Shift & Attendance")
	changed = False
	label = "Leave Calendar"
	if not any(row.type == "Page" and row.link_to == "leave-calendar" for row in workspace.shortcuts):
		workspace.append("shortcuts", {"type": "Page", "label": label, "link_to": "leave-calendar", "color": "Blue"})
		changed = True
	content = frappe.parse_json(workspace.content or "[]")
	if not any(block.get("type") == "shortcut" and block.get("data", {}).get("shortcut_name") == label for block in content):
		content.append({"id": "leaveCalendar1", "type": "shortcut", "data": {"shortcut_name": label, "col": 4}})
		workspace.content = frappe.as_json(content)
		changed = True
	if changed:
		workspace.content = frappe.as_json(content)
		workspace.save(ignore_permissions=True)
