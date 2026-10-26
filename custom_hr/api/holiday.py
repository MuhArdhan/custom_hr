# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Bulk Holiday List Assignment: put many Companies or Employees on one Holiday List."""

import frappe
from frappe import _
from frappe.utils import getdate, today

HOLIDAY_ROLES = ("HR Manager", "HR User", "System Manager")
KINDS = ("Company", "Employee")


def _assignments(kind, as_on, assigned_to=None):
	filters = {"applicable_for": kind, "docstatus": 1, "from_date": ["<=", as_on]}
	if assigned_to:
		filters["assigned_to"] = assigned_to
	return frappe.get_all(
		"Holiday List Assignment",
		filters=filters,
		fields=["assigned_to", "holiday_list", "from_date"],
		order_by="from_date desc",
	)


@frappe.whitelist()
def get_holiday_targets(holiday_list, kind):
	"""Every Company/Employee with the Holiday List it uses today, and whether that is `holiday_list`."""
	frappe.only_for(HOLIDAY_ROLES)
	if kind not in KINDS:
		frappe.throw(_("Kind must be Company or Employee"))

	current = {}
	for row in _assignments(kind, getdate(today())):
		current.setdefault(row.assigned_to, row.holiday_list)  # newest first

	if kind == "Company":
		targets = [{"name": name, "label": name} for name in frappe.get_all("Company", pluck="name", order_by="name")]
	else:
		targets = [
			{"name": e.name, "label": f"{e.employee_name} ({e.name})"}
			for e in frappe.get_all("Employee", filters={"status": "Active"}, fields=["name", "employee_name"], order_by="employee_name")
		]
	for target in targets:
		target["holiday_list"] = current.get(target["name"])
		target["on_list"] = target["holiday_list"] == holiday_list
	return targets


@frappe.whitelist(methods=["POST"])
def assign_holiday_list(holiday_list, kind, targets, from_date):
	"""Add a submitted assignment per target; targets already on the list from `from_date` are left alone."""
	frappe.only_for(HOLIDAY_ROLES)
	if kind not in KINDS:
		frappe.throw(_("Kind must be Company or Employee"))
	if not from_date:
		frappe.throw(_("From Date is required"))
	if not frappe.db.exists("Holiday List", holiday_list):
		frappe.throw(_("Holiday List {0} does not exist").format(holiday_list))
	if isinstance(targets, str):
		targets = frappe.parse_json(targets)

	result = {"assigned": 0, "unchanged": 0, "failed": []}
	for target in dict.fromkeys(targets):  # drop repeats, keep order
		current = _assignments(kind, from_date, target)
		if current and current[0].holiday_list == holiday_list:
			result["unchanged"] += 1
			continue
		frappe.db.savepoint("holiday_assign")
		try:
			frappe.get_doc(
				{
					"doctype": "Holiday List Assignment",
					"applicable_for": kind,
					"assigned_to": target,
					"holiday_list": holiday_list,
					"from_date": from_date,
				}
			).insert().submit()
			result["assigned"] += 1
		except Exception as e:
			frappe.db.rollback(save_point="holiday_assign")
			result["failed"].append({"target": target, "error": frappe.utils.strip_html(str(e))})
	frappe.db.commit()
	return result
