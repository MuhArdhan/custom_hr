"""Repair stored Outlet radius displays from their linked native masters."""

import frappe

from custom_hr.services.outlet_location import sync_location_radius_to_outlet


def execute():
	for name in frappe.get_all("Shift Location", pluck="name"):
		sync_location_radius_to_outlet(frappe.get_doc("Shift Location", name))
