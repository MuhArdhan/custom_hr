# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Outlet APIs: sync outlets from the Company tree, bulk-provision employees."""

import frappe
from frappe.utils import getdate, today

EXCLUDED_COMPANIES = frozenset(
	["JURI GROUP", "PT. JUARA ROTI INDONESIA", "OUTLET", "TRAINING", "OUTLET PAMERAN"]
)
OUTLET_ROLES = ("HR Manager", "HR User", "System Manager")


@frappe.whitelist()
def sync_outlets_from_companies():
	"""Create an Outlet for every leaf Company except the group's own entities."""
	frappe.only_for(OUTLET_ROLES)

	companies = frappe.get_all("Company", filters={"is_group": 0}, pluck="name")
	created = 0
	for company in companies:
		if company in EXCLUDED_COMPANIES or frappe.db.exists("Outlet", company):
			continue
		frappe.get_doc({"doctype": "Outlet", "company": company}).insert(ignore_permissions=True)
		created += 1

	frappe.db.commit()
	return {"created": created, "companies": len(companies)}


@frappe.whitelist()
def provision_outlet(outlet):
	"""Assign the outlet's holiday list to all active employees of the outlet."""
	frappe.only_for(OUTLET_ROLES)

	outlet_doc = frappe.get_doc("Outlet", outlet)
	employees = frappe.get_all(
		"Employee", filters={"outlet": outlet, "status": "Active"}, pluck="name"
	)
	assigned = 0
	for employee in employees:
		if outlet_doc.holiday_list and _assign_holiday_list(employee, outlet_doc.holiday_list):
			assigned += 1

	frappe.db.commit()
	return {"employees": len(employees), "holidays_assigned": assigned}


@frappe.whitelist()
def get_shift_outlets(shift_type):
	"""Every active outlet, flagged when it already has `shift_type` (Shift Type bulk tool)."""
	frappe.only_for(OUTLET_ROLES)

	outlets = frappe.get_all("Outlet", filters={"is_active": 1}, pluck="name", order_by="name")
	with_shift = set(
		frappe.get_all(
			"Outlet Shift", filters={"parenttype": "Outlet", "shift_type": shift_type}, pluck="parent"
		)
	)
	return [{"outlet": name, "has_shift": name in with_shift} for name in outlets]


@frappe.whitelist(methods=["POST"])
def set_shift_outlets(shift_type, add=None, remove=None):
	"""Attach `shift_type` (enabled) to the `add` outlets and detach it from the `remove` ones.

	The client sends only its own diff, so an outlet changed by someone else in the meantime
	is left alone ("unchanged"). Outlets are saved through the document so Outlet.validate
	still applies; an invalid outlet is rolled back and reported without stopping the others.
	"""
	frappe.only_for(OUTLET_ROLES)
	if not frappe.db.exists("Shift Type", shift_type):
		frappe.throw(frappe._("Shift Type {0} tidak ditemukan.").format(shift_type))
	add = list(dict.fromkeys(frappe.parse_json(add) or []))
	remove = list(dict.fromkeys(frappe.parse_json(remove) or []))
	if set(add) & set(remove):
		frappe.throw(frappe._("Outlet tidak boleh ada di daftar tambah dan hapus sekaligus."))

	result = {"added": 0, "removed": 0, "unchanged": 0, "failed": []}
	for name, adding in [(name, True) for name in add] + [(name, False) for name in remove]:
		doc = frappe.get_doc("Outlet", name)
		rows = [row for row in doc.shifts if row.shift_type == shift_type]
		if bool(rows) == adding:
			result["unchanged"] += 1
			continue
		frappe.db.savepoint("set_outlet_shift")
		try:
			if adding:
				doc.append("shifts", {"shift_type": shift_type, "enabled": 1})
			else:
				for row in rows:
					doc.remove(row)
			doc.save(ignore_permissions=True)
		except frappe.ValidationError as error:
			frappe.db.rollback(save_point="set_outlet_shift")
			frappe.clear_messages()
			result["failed"].append({"outlet": name, "error": str(error)})
		else:
			result["added" if adding else "removed"] += 1

	frappe.db.commit()
	return result


def _assign_holiday_list(employee, holiday_list):
	if frappe.db.exists(
		"Holiday List Assignment",
		{
			"applicable_for": "Employee",
			"assigned_to": employee,
			"holiday_list": holiday_list,
			"docstatus": 1,
		},
	):
		return False

	holiday = frappe.get_doc("Holiday List", holiday_list)
	assignment = frappe.new_doc("Holiday List Assignment")
	assignment.holiday_list = holiday_list
	assignment.applicable_for = "Employee"
	assignment.assigned_to = employee
	assignment.from_date = max(getdate(holiday.from_date), getdate(today()))
	assignment.insert(ignore_permissions=True)
	if assignment.meta.is_submittable:
		assignment.submit()
	return True
