"""Payroll period input: one grid for the monthly Additional Salary amounts HR decides per employee.

Rows are employees with a Salary Structure Assignment, columns are the Salary Components ticked
"Tampil di Input Additional Salary". Saving only creates or cancels native Additional Salary.
"""

import json
from collections import defaultdict
from datetime import date

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate

from custom_hr.api import require_page_access

PAGE = "payroll-period-input"
CUTOFF_DAY = 25  # outlet period runs from the 26th of the previous month to the 25th


def period_bounds(month: str) -> tuple[date, date]:
	"""'2026-10' -> 26 Sep 2026 .. 25 Oct 2026."""
	try:
		year, mon = (int(part) for part in str(month).split("-")[:2])
		end = date(year, mon, CUTOFF_DAY)
	except ValueError:
		frappe.throw(_("Periode harus berformat YYYY-MM."))
	return getdate(add_months(end, -1)).replace(day=CUTOFF_DAY + 1), end


def plan_cell(existing: list[float], amount: float | None) -> str:
	"""What saving one cell does: keep, create, replace, cancel, or refuse when it holds several entries."""
	if len(existing) > 1:
		return "locked"
	current = existing[0] if existing else None
	if not amount:
		return "cancel" if current else "keep"
	if current is None:
		return "create"
	return "keep" if flt(current) == flt(amount) else "replace"


def _components() -> list[dict]:
	return frappe.get_all(
		"Salary Component",
		filters={"show_in_period_input": 1, "disabled": 0},
		fields=["name", "salary_component_abbr as abbr", "type"],
		order_by="type desc, name asc",  # earnings first, then deductions
	)


def _employees(start, end, company=None, search=None) -> list[dict]:
	ssa = frappe.qb.DocType("Salary Structure Assignment")
	emp = frappe.qb.DocType("Employee")
	query = (
		frappe.qb.from_(ssa)
		.join(emp)
		.on(emp.name == ssa.employee)
		.select(emp.name.as_("employee"), emp.employee_name, ssa.company)
		.distinct()
		.where((ssa.docstatus == 1) & (ssa.from_date <= end))
		.where((emp.status == "Active") | (emp.relieving_date >= start))
		.orderby(ssa.company)
		.orderby(emp.employee_name)
	)
	if company:
		query = query.where(ssa.company == company)
	if search:
		query = query.where(emp.employee_name.like(f"%{search}%") | emp.name.like(f"%{search}%"))
	return query.run(as_dict=True)


def _additional_salaries(employees, components, start, end) -> dict:
	cells = defaultdict(list)
	if not employees or not components:
		return cells
	for row in frappe.get_all(
		"Additional Salary",
		filters={
			"docstatus": 1,
			"is_recurring": 0,
			"employee": ["in", employees],
			"salary_component": ["in", components],
			"payroll_date": ["between", [start, end]],
		},
		fields=["name", "employee", "salary_component", "amount"],
	):
		cells[(row.employee, row.salary_component)].append(row)
	return cells


def _paid_employees(employees, start, end) -> set:
	"""A submitted slip for the period fixes its Additional Salary: those rows are read-only."""
	if not employees:
		return set()
	return set(
		frappe.get_all(
			"Salary Slip",
			filters={"docstatus": 1, "employee": ["in", employees], "start_date": ["<=", end], "end_date": [">=", start]},
			pluck="employee",
		)
	)


def _attendance(employees, start, end) -> dict:
	if not employees:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT employee,
			SUM(status IN ('Present', 'Work From Home')) + 0.5 * SUM(status = 'Half Day') AS hadir,
			SUM(late_entry) AS telat, SUM(early_exit) AS pulang_cepat, SUM(missing_checkout) AS tidak_out
		FROM `tabAttendance`
		WHERE docstatus = 1 AND employee IN %(employees)s AND attendance_date BETWEEN %(start)s AND %(end)s
		GROUP BY employee
		""",
		{"employees": tuple(employees), "start": start, "end": end},
		as_dict=True,
	)
	return {row.employee: row for row in rows}


@frappe.whitelist(methods=["GET"])
def get_period_input(month: str, company: str | None = None, search: str | None = None) -> dict:
	require_page_access(PAGE)
	start, end = period_bounds(month)
	components = _components()
	employees = _employees(start, end, company, search)
	names = [row.employee for row in employees]
	cells = _additional_salaries(names, [c.name for c in components], start, end)
	paid = _paid_employees(names, start, end)
	attendance = _attendance(names, start, end)
	for row in employees:
		row.locked = row.employee in paid
		row.attendance = attendance.get(row.employee) or {}
		row.amounts = {}
		for component in components:
			entries = cells.get((row.employee, component.name), [])
			row.amounts[component.name] = {
				"amount": sum(flt(entry.amount) for entry in entries),
				"multiple": len(entries) > 1,
			}
	return {"start": start, "end": end, "components": components, "rows": employees}


@frappe.whitelist(methods=["POST"])
def save_period_input(month: str, changes: str | list) -> dict:
	"""Each change is {employee, component, amount}. All or nothing: any refusal rolls the request back."""
	require_page_access(PAGE)
	changes = json.loads(changes) if isinstance(changes, str) else changes
	start, end = period_bounds(month)
	allowed = {c.name for c in _components()}
	employees = sorted({change["employee"] for change in changes})
	cells = _additional_salaries(employees, list(allowed), start, end)
	paid = _paid_employees(employees, start, end)
	companies = dict(frappe.get_all("Employee", filters={"name": ["in", employees]}, fields=["name", "company"], as_list=True))
	result = defaultdict(int)

	for change in changes:
		employee, component = change["employee"], change["component"]
		amount = flt(change.get("amount"))
		if component not in allowed:
			frappe.throw(_("Komponen {0} tidak tampil di Input Additional Salary.").format(component))
		if amount < 0:
			frappe.throw(_("Nilai {0} untuk {1} tidak boleh minus.").format(component, employee))
		if employee in paid:
			frappe.throw(_("Slip gaji {0} periode ini sudah disubmit.").format(employee))
		existing = cells.get((employee, component), [])
		action = plan_cell([entry.amount for entry in existing], amount)
		if action == "locked":
			frappe.throw(_("{0} punya lebih dari satu Additional Salary {1} di periode ini. Rapikan dari daftar Additional Salary.").format(employee, component))
		if action in ("cancel", "replace"):
			frappe.get_doc("Additional Salary", existing[0].name).cancel()
		if action in ("create", "replace"):
			frappe.get_doc(
				{
					"doctype": "Additional Salary",
					"employee": employee,
					"company": companies[employee],
					"salary_component": component,
					"amount": amount,
					"payroll_date": end,
					"overwrite_salary_structure_amount": 0,
				}
			).submit()
		result[action] += 1
	return dict(result)
