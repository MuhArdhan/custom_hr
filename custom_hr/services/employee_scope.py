"""Outlet vs Non-Outlet/Department scoping for Overtime Type, Leave Type, and Shift Type."""

from __future__ import annotations

import frappe
from frappe import _
SCOPE_ALL = "Semua"
SCOPE_OUTLET = "Khusus Outlet"
SCOPE_NON_OUTLET = "Khusus Non-Outlet"


def matches_scope(rule, *, outlet: str | None = None, department: str | None = None) -> bool:
	"""Return True when a rule's berlaku_untuk / hanya_department allows the given employee placement."""
	if not isinstance(rule, dict):
		return True
	scope = (rule.get("berlaku_untuk") or SCOPE_ALL).strip()
	has_outlet = bool(outlet)
	if scope == SCOPE_OUTLET and not has_outlet:
		return False
	if scope == SCOPE_NON_OUTLET and has_outlet:
		return False
	req_dept = (rule.get("hanya_department") or "").strip()
	if req_dept and (department or "").strip() != req_dept:
		return False
	return True


def employee_scope_info(employee: str | None) -> dict:
	if not employee:
		return frappe._dict()
	info = frappe.db.get_value("Employee", employee, ["outlet", "department", "company"], as_dict=True)
	return info if isinstance(info, dict) else frappe._dict()


def allowed_overtime_types(*, outlet: str | None = None, department: str | None = None) -> list[dict]:
	"""Active Overtime Types filtered by outlet/department applicability."""
	rows = frappe.get_all(
		"Overtime Type",
		filters={"disabled": 0},
		fields=["name", "maximum_overtime_hours_allowed as max_hours", "berlaku_untuk", "hanya_department"],
		order_by="name asc",
	)
	return [
		{"name": row.name, "max_hours": row.get("max_hours") or 0}
		for row in rows
		if matches_scope(row, outlet=outlet, department=department)
	]


def validate_overtime_type_scope(
	overtime_type: str | None,
	*,
	outlet: str | None = None,
	departments: list[str | None] | None = None,
) -> None:
	if not overtime_type:
		return
	rule = frappe.db.get_value(
		"Overtime Type",
		overtime_type,
		["berlaku_untuk", "hanya_department"],
		as_dict=True,
	)
	if not isinstance(rule, dict):
		return
	depts = departments if departments is not None else [None]
	for dept in depts:
		if not matches_scope(rule, outlet=outlet, department=dept):
			frappe.throw(
				_("Jenis lembur {0} tidak berlaku untuk outlet/departemen yang dipilih.").format(overtime_type)
			)


def filter_leave_types(leave_type_names: list[str], *, outlet: str | None = None, department: str | None = None) -> list[str]:
	if not leave_type_names:
		return []
	rules = {
		row.name: row
		for row in frappe.get_all(
			"Leave Type",
			filters={"name": ["in", leave_type_names]},
			fields=["name", "berlaku_untuk", "hanya_department"],
		)
	}
	return [
		name
		for name in leave_type_names
		if matches_scope(rules.get(name) or {}, outlet=outlet, department=department)
	]


def validate_leave_application_scope(doc, method=None) -> None:
	"""Leave Application before_validate: block Leave Types restricted to a different outlet/department."""
	if not doc.get("employee") or not doc.get("leave_type"):
		return
	if not (doc.is_new() or doc.has_value_changed("leave_type")):
		return
	rule = frappe.db.get_value(
		"Leave Type",
		doc.leave_type,
		["berlaku_untuk", "hanya_department"],
		as_dict=True,
	)
	if not isinstance(rule, dict):
		return
	info = employee_scope_info(doc.employee)
	if not matches_scope(rule, outlet=info.get("outlet"), department=info.get("department")):
		frappe.throw(
			_("Jenis izin/cuti {0} tidak berlaku untuk outlet/departemen karyawan ini.").format(doc.leave_type)
		)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def overtime_type_query(doctype, txt, searchfield, start, page_len, filters):
	company = (filters or {}).get("company")
	outlet = company if company and frappe.db.exists("Outlet", company) else None
	rows = frappe.get_all(
		"Overtime Type",
		filters={"disabled": 0, "name": ["like", f"%{txt or ''}%"]},
		fields=["name", "berlaku_untuk", "hanya_department"],
		order_by="name asc",
	)
	if company:
		rows = [
			r for r in rows
			if (r.get("berlaku_untuk") or SCOPE_ALL) == SCOPE_ALL
			or ((r.get("berlaku_untuk") == SCOPE_OUTLET) == bool(outlet))
		]
	return [(r.name,) for r in rows[int(start or 0) : int(start or 0) + int(page_len or 20)]]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def leave_type_query(doctype, txt, searchfield, start, page_len, filters):
	employee = (filters or {}).get("employee")
	info = employee_scope_info(employee)
	rows = frappe.get_all(
		"Leave Type",
		filters={"name": ["like", f"%{txt or ''}%"]},
		fields=["name", "berlaku_untuk", "hanya_department"],
		order_by="name asc",
	)
	if employee:
		rows = [r for r in rows if matches_scope(r, outlet=info.get("outlet"), department=info.get("department"))]
	return [(r.name,) for r in rows[int(start or 0) : int(start or 0) + int(page_len or 20)]]

