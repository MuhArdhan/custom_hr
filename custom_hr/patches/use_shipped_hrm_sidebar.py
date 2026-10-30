"""Let the HRM sidebar shipped in hrm/sidebar/ replace a copy Frappe converted from the old Workspace Sidebar.

A converted copy can be newer than the shipped file and would then be kept; aging it makes the sync import the file.
"""

import frappe


def execute():
	if frappe.db.table_exists("Sidebar") and frappe.db.get_value("Sidebar", "HRM", "standard") == 0:
		frappe.db.set_value("Sidebar", "HRM", "modified", "2000-01-01 00:00:00", update_modified=False)
