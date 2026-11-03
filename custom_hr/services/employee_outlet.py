"""Employee.outlet defaults to the Outlet of the Employee's Company."""

import frappe


def fill_outlet(doc, method=None):
	"""Employee validate: Outlets are named after their Company, so only fill when that Outlet exists."""
	if doc.company and not doc.outlet and frappe.db.exists("Outlet", doc.company):
		doc.outlet = doc.company


@frappe.whitelist()
def get_current_employee_info() -> dict:
	"""hrms.api.get_current_employee_info plus the Outlet, so the app can tell outlet from department staff."""
	from hrms.api import get_current_employee_info as hrms_get_current_employee_info

	info = hrms_get_current_employee_info()
	if info:
		info["outlet"] = frappe.db.get_value("Employee", info["name"], "outlet")
	return info
