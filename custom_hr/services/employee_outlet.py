"""Employee.outlet defaults to the Outlet of the Employee's Company."""

import frappe


def fill_outlet(doc, method=None):
	"""Employee validate: Outlets are named after their Company, so only fill when that Outlet exists."""
	if doc.company and not doc.outlet and frappe.db.exists("Outlet", doc.company):
		doc.outlet = doc.company
