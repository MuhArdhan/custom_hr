"""Install-time setup that needs the app's fixtures to exist."""

import frappe

SETTINGS = "HRM Payroll Settings"
FIELD = "overtime_salary_component"
COMPONENT = "Lembur"


def set_default_overtime_component():
	"""after_sync runs after fixtures; init_singles() runs before them and cannot link to Lembur."""
	if frappe.db.get_single_value(SETTINGS, FIELD) or not frappe.db.exists("Salary Component", COMPONENT):
		return
	frappe.db.set_single_value(SETTINGS, FIELD, COMPONENT)
