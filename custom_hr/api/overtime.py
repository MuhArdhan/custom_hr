# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Row-level permissions for Overtime Request: HR roles see everything,
everyone else only sees requests of outlets where they are an approver, or that name them as an approver."""

import frappe

from custom_hr.api.roster import HR_ROLES


def get_permission_query_conditions(user=None, doctype="Overtime Request"):
	user = user or frappe.session.user
	if _sees_all(user):
		return ""
	me = frappe.db.escape(user)
	# Non-outlet requests have no outlet to scope by: their recorded (Department) approvers see them.
	recorded = f"`tabOvertime Request`.`approver_1` = {me} or `tabOvertime Request`.`approver_2` = {me}"
	if doctype == "Overtime List":
		recorded = f"`tabOvertime List`.`overtime_request` in (select `tabOvertime Request`.`name` from `tabOvertime Request` where {recorded})"
	outlets = _their_outlets(user)
	if not outlets:
		return f"({recorded})"
	escaped = ", ".join(frappe.db.escape(outlet) for outlet in outlets)
	return f"(`tab{doctype}`.`outlet` in ({escaped}) or {recorded})"


def get_list_permission_query_conditions(user=None):
	"""Overtime List rows carry their request's outlet and request, so they follow the same scope."""
	return get_permission_query_conditions(user, "Overtime List")


def has_permission(doc, ptype="read", user=None, debug=False):
	"""Controller permission hook.

	V16 semantics: True allows, anything falsy denies. An outlet request opens for
	that outlet's approvers; a saved non-outlet request for its recorded approvers
	and its creator. Creating is checked by OvertimeRequest.guard_create_access.
	"""
	user = user or frappe.session.user
	if _sees_all(user):
		return True
	if not hasattr(doc, "get"):
		return True
	outlet = doc.get("outlet")
	if outlet:
		return outlet in _their_outlets(user)
	if ptype == "create" or not doc.get("name"):
		return True
	if doc.get("doctype") == "Overtime List":  # a list row carries only its request
		return user in (frappe.db.get_value("Overtime Request", doc.get("overtime_request"), ["approver_1", "approver_2", "owner"]) or ())
	return user in (doc.get("approver_1"), doc.get("approver_2"), doc.get("owner"))


def _sees_all(user):
	return user == "Administrator" or bool(set(HR_ROLES) & set(frappe.get_roles(user)))


def _their_outlets(user):
	return frappe.get_all(
		"Outlet",
		filters={"is_active": 1},
		or_filters=[["approver_1", "=", user], ["approver_2", "=", user]],
		pluck="name",
		ignore_permissions=True,
	)
