"""Cross-company Salary Structure scoping driven by Employee.outlet and Department."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from custom_hr.services.employee_scope import SCOPE_ALL, SCOPE_OUTLET, employee_scope_info, matches_scope


def validate_salary_structure(doc, method=None) -> None:
	"""Salary Structure validate / on_update_after_submit: keep global scope and accounts consistent."""
	if (doc.get("berlaku_untuk") or SCOPE_ALL).strip() == SCOPE_OUTLET:
		doc.hanya_department = None
	if cint(doc.get("lintas_company")) and doc.get("payment_account"):
		frappe.throw(
			_(
				"Struktur gaji Lintas Company harus mengosongkan Payment Account agar memakai akun perusahaan masing-masing."
			)
		)


def validate_assignment_scope(assignment) -> None:
	"""Salary Structure Assignment validate_company override supporting lintas_company and outlet placement."""
	if not assignment.get("salary_structure"):
		return
	ss = frappe.db.get_value(
		"Salary Structure",
		assignment.salary_structure,
		["company", "lintas_company", "berlaku_untuk", "hanya_department"],
		as_dict=True,
	)
	if not ss:
		return
	if not cint(ss.get("lintas_company")) and assignment.company != ss.company:
		frappe.throw(
			_("Salary Structure {0} does not belong to company {1}").format(
				frappe.bold(assignment.salary_structure), frappe.bold(assignment.company)
			)
		)
	info = employee_scope_info(assignment.get("employee"))
	if assignment.get("employee") and not matches_scope(ss, outlet=info.get("outlet"), department=info.get("department")):
		frappe.throw(
			_("Struktur gaji {0} tidak berlaku untuk penempatan outlet/departemen karyawan ini.").format(
				frappe.bold(assignment.salary_structure)
			)
		)


def get_applicable_salary_structures(
	company: str, currency: str, salary_slip_based_on_timesheet: int, payroll_frequency: str
) -> list[str]:
	"""Submitted active Salary Structures for company OR marked lintas_company=1."""
	SalaryStructure = frappe.qb.DocType("Salary Structure")
	query = (
		frappe.qb.from_(SalaryStructure)
		.select(SalaryStructure.name)
		.where(
			(SalaryStructure.docstatus == 1)
			& (SalaryStructure.is_active == "Yes")
			& ((SalaryStructure.company == company) | (SalaryStructure.lintas_company == 1))
			& (SalaryStructure.currency == currency)
			& (SalaryStructure.salary_slip_based_on_timesheet == salary_slip_based_on_timesheet)
		)
	)
	if not salary_slip_based_on_timesheet:
		query = query.where(SalaryStructure.payroll_frequency == payroll_frequency)
	return query.run(pluck=True)


def _matches_filter_scope(rule, *, employee: str | None, outlet: str | None, department: str | None) -> bool:
	if employee:
		return matches_scope(rule, outlet=outlet, department=department)
	scope = (rule.get("berlaku_untuk") or SCOPE_ALL).strip()
	if scope == SCOPE_OUTLET and not outlet:
		return False
	if scope != SCOPE_ALL and scope != SCOPE_OUTLET and outlet:
		return False
	req_dept = (rule.get("hanya_department") or "").strip()
	if req_dept and department and department.strip() != req_dept:
		return False
	return True


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def salary_structure_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link query returning own-company or lintas_company active Salary Structures matching outlet/dept scope."""
	filters = filters or {}
	company = filters.get("company")
	employee = filters.get("employee")
	department = filters.get("department")

	outlet = None
	if employee:
		info = employee_scope_info(employee)
		outlet = info.get("outlet")
		department = info.get("department")
		company = company or info.get("company")
	elif company:
		outlet = company if frappe.db.exists("Outlet", company) else None

	rows = frappe.get_all(
		"Salary Structure",
		filters={"docstatus": 1, "is_active": "Yes", "name": ["like", f"%{txt or ''}%"]},
		fields=["name", "company", "lintas_company", "berlaku_untuk", "hanya_department"],
		order_by="name asc",
	)
	if company:
		rows = [r for r in rows if r.company == company or cint(r.get("lintas_company"))]
	if employee or company:
		rows = [
			r
			for r in rows
			if _matches_filter_scope(r, employee=employee, outlet=outlet, department=department)
		]

	offset = int(start or 0)
	limit = int(page_len or 20)
	return [(r.name,) for r in rows[offset : offset + limit]]
