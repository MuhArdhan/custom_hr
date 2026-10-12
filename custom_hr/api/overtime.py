# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Row-level permissions for Overtime Request: HR roles see everything,
everyone else only sees requests of outlets where they are an approver."""

import frappe

from custom_hr.api.roster import HR_ROLES


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _sees_all(user):
		return ""
	outlets = _their_outlets(user)
	if not outlets:
		return "1=0"
	escaped = ", ".join(frappe.db.escape(outlet) for outlet in outlets)
	return "`tabOvertime Request`.`outlet` in ({0})".format(escaped)


def has_permission(doc, ptype="read", user=None, debug=False):
	"""Controller permission hook.

	V16 semantics: True allows, anything falsy denies. Only restrict when the
	document actually carries an outlet the user is not an approver of.
	"""
	user = user or frappe.session.user
	if _sees_all(user):
		return True
	outlet = doc.get("outlet") if hasattr(doc, "get") else None
	if not outlet:
		return True
	return outlet in _their_outlets(user)


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
