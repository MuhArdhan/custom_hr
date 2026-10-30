"""The HRM app icon opens the HRM workspace instead of the attendance gallery."""

import frappe

OLD, NEW = "/app/employee-attendance-gallery", "/app/hrm"


def execute():
	if frappe.db.exists("DocType", "Desktop Icon"):
		frappe.db.set_value("Desktop Icon", {"link": OLD}, "link", NEW)
		frappe.cache.delete_key("desktop_icons")
