"""Migrate the legacy Page/links to Leave Calendar, without touching leave data."""

import frappe

from custom_hr.patches.add_leave_calendar import execute as update_workspace


def execute():
	# Legacy names exist only here so existing installations can migrate safely.
	old_page, new_page = "approval-calendar", "leave-calendar"
	if frappe.db.exists("Page", old_page):
		old = frappe.get_doc("Page", old_page)
		if old.module != "HRM":
			frappe.throw("Legacy calendar page belongs to another module; review before renaming.")
		if frappe.db.exists("Page", new_page):
			new = frappe.get_doc("Page", new_page)
			if new.module != "HRM":
				frappe.throw("Leave Calendar page already exists in another module.")
			roles = {r.role for r in new.roles}
			for row in old.roles:
				if row.role not in roles:
					new.append("roles", {"role": row.role})
					roles.add(row.role)
			new.flags.do_not_update_json = True
			new.save(ignore_permissions=True)
		frappe.rename_doc("Page", old_page, new_page, force=True,
			merge=bool(frappe.db.exists("Page", new_page)))
	if not frappe.db.exists("Page", new_page):
		frappe.reload_doc("hrm", "page", "leave_calendar")
	frappe.db.set_value("Page", new_page, {"page_name": new_page, "title": "Leave Calendar"}, update_modified=False)
	if frappe.db.exists("Workspace", "Shift & Attendance"):
		workspace = frappe.get_doc("Workspace", "Shift & Attendance")
		changed = False
		old_labels = {"Kalender Approval", "Kalender Cuti & Izin"}
		for shortcut in workspace.shortcuts:
			if shortcut.type == "Page" and shortcut.link_to in {old_page, new_page}:
				if shortcut.link_to != new_page or shortcut.label in old_labels:
					shortcut.link_to = new_page
					shortcut.label = "Leave Calendar"
					changed = True
		content = frappe.parse_json(workspace.content or "[]")
		for block in content:
			if block.get("type") == "shortcut":
				data = block.get("data", {})
				if data.get("shortcut_name") in old_labels:
					data["shortcut_name"] = "Leave Calendar"
					changed = True
				if block.get("id") == "approvalCalendar1":
					block["id"] = "leaveCalendar1"
					changed = True
		if changed:
			workspace.content = frappe.as_json(content)
			workspace.save(ignore_permissions=True)
	update_workspace()
	frappe.clear_cache(doctype="Page")
