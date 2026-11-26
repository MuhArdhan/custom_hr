"""Bulk Deduct from Salary for paid Employee Advances with 'Repay Unclaimed Amount from Salary'."""

import json
from datetime import date

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate
from hrms.hr.doctype.employee_advance.employee_advance import create_return_through_additional_salary

from custom_hr.api.payroll_input import CUTOFF_DAY


def _require() -> None:
	if not (frappe.has_permission("Employee Advance", "read") and frappe.has_permission("Additional Salary", "submit")):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _default_payroll_date(today: date | None = None) -> date:
	"""Current payroll cutoff date (25th of this month, or next month after the 25th)."""
	ref = getdate(today) if today else getdate()
	base = ref.replace(day=1)
	if ref.day > CUTOFF_DAY:
		base = getdate(add_months(base, 1))
	return base.replace(day=CUTOFF_DAY)


def _scheduled_returns(advance_names: list[str]) -> dict[str, float]:
	"""Submitted Additional Salary amounts already linked to each Employee Advance."""
	if not advance_names:
		return {}
	rows = frappe.get_all(
		"Additional Salary",
		filters={
			"docstatus": 1,
			"ref_doctype": "Employee Advance",
			"ref_docname": ["in", advance_names],
		},
		fields=["ref_docname", "amount"],
	)
	totals: dict[str, float] = {}
	for row in rows:
		totals[row.ref_docname] = flt(totals.get(row.ref_docname, 0) + flt(row.amount), 2)
	return totals


def eligible_advances(rows: list | None = None, scheduled: dict[str, float] | None = None) -> list[dict]:
	"""Return paid Employee Advances still having an unscheduled return balance."""
	if rows is None:
		rows = frappe.get_all(
			"Employee Advance",
			filters={
				"docstatus": 1,
				"repay_unclaimed_amount_from_salary": 1,
				"status": ["in", ["Paid", "Partly Claimed and Returned"]],
			},
			fields=[
				"name",
				"employee",
				"employee_name",
				"company",
				"currency",
				"posting_date",
				"advance_account",
				"paid_amount",
				"claimed_amount",
			],
			order_by="company asc, posting_date asc, employee_name asc",
		)
	if scheduled is None:
		scheduled = _scheduled_returns([row.name for row in rows])

	eligible = []
	for row in rows:
		sched = flt(scheduled.get(row.name), 2)
		remaining = flt(flt(row.paid_amount) - flt(row.claimed_amount) - sched, 2)
		if remaining <= 0:
			continue
		eligible.append(
			{
				"name": row.name,
				"employee": row.employee,
				"employee_name": row.employee_name,
				"company": row.company,
				"currency": row.currency,
				"posting_date": str(row.posting_date),
				"advance_account": row.get("advance_account"),
				"paid_amount": flt(row.paid_amount, 2),
				"claimed_amount": flt(row.claimed_amount, 2),
				"scheduled_amount": sched,
				"remaining_amount": remaining,
			}
		)
	return eligible


def _recalculate_draft_slips(employees: set[str], payroll_date: date) -> int:
	"""Re-save draft Salary Slips covering payroll_date so newly submitted Additional Salaries apply immediately."""
	if not employees:
		return 0
	slips = frappe.get_all(
		"Salary Slip",
		filters={
			"docstatus": 0,
			"employee": ["in", sorted(employees)],
			"start_date": ["<=", payroll_date],
			"end_date": [">=", payroll_date],
		},
		pluck="name",
	)
	for name in slips:
		frappe.get_doc("Salary Slip", name).save()
	return len(slips)


def _active_deduction(component: str | None) -> str | None:
	if not component:
		return None
	info = frappe.db.get_value("Salary Component", component, ["name", "type", "disabled"], as_dict=True)
	return info.name if info and info.type == "Deduction" and not info.disabled else None


def _default_deduct_component(advances: list[dict]) -> str | None:
	"""Resolve default Deduction component from prior advance returns or Payroll Settings account mapping."""
	last_used = frappe.get_all(
		"Additional Salary",
		filters={"docstatus": 1, "ref_doctype": "Employee Advance"},
		pluck="salary_component",
		order_by="creation desc",
		limit=1,
	)
	if last_used:
		comp = _active_deduction(last_used[0])
		if comp:
			return comp

	accounts = {row.get("advance_account") for row in advances if row.get("advance_account")}
	numbers = {
		frappe.db.get_value("Account", acct, "account_number")
		for acct in accounts
	} - {None, ""}
	if numbers:
		settings = frappe.get_cached_doc("Payroll Settings")
		for row in settings.get("component_accounts") or ():
			if (row.account_number or "").strip() in numbers:
				comp = _active_deduction(row.salary_component)
				if comp:
					return comp
	return None


@frappe.whitelist(methods=["GET"])
def get_deduct_targets() -> dict:
	_require()
	advances = eligible_advances()
	return {
		"advances": advances,
		"default_component": _default_deduct_component(advances),
		"default_payroll_date": str(_default_payroll_date()),
	}


@frappe.whitelist(methods=["POST"])
def bulk_deduct_from_salary(advances: str | list, salary_component: str, payroll_date: str) -> dict:
	"""Create & submit native Additional Salary return entries for each selected Employee Advance."""
	_require()
	names = json.loads(advances) if isinstance(advances, str) else list(advances or [])
	names = list(dict.fromkeys(str(n) for n in names if n))
	if not names:
		frappe.throw(_("Pilih minimal satu Employee Advance."))

	comp = frappe.db.get_value("Salary Component", salary_component, ["name", "type", "disabled"], as_dict=True)
	if not comp or comp.disabled or comp.type != "Deduction":
		frappe.throw(_("Komponen gaji {0} harus aktif dan bertipe Deduction.").format(salary_component or "''"))
	target_date = getdate(payroll_date)

	scheduled = _scheduled_returns(names)
	created, errors, affected_employees = [], [], set()
	for idx, adv_name in enumerate(names):
		sp = f"ea_bulk_{idx}"
		frappe.db.savepoint(sp)
		try:
			adv = frappe.get_doc("Employee Advance", adv_name)
			if adv.docstatus != 1 or not adv.repay_unclaimed_amount_from_salary:
				frappe.throw(_("{0} belum berstatus Paid dengan Repay Unclaimed Amount from Salary.").format(adv_name))
			remaining = flt(flt(adv.paid_amount) - flt(adv.claimed_amount) - flt(scheduled.get(adv_name)), 2)
			if remaining <= 0:
				frappe.throw(_("{0} sudah tidak memiliki sisa yang belum dijadwalkan.").format(adv_name))

			add_sal = create_return_through_additional_salary(adv)
			add_sal.salary_component = comp.name
			add_sal.payroll_date = target_date
			add_sal.amount = remaining
			add_sal.insert()
			add_sal.submit()
			scheduled[adv_name] = flt(scheduled.get(adv_name, 0) + remaining, 2)
			affected_employees.add(adv.employee)
			created.append(
				{
					"name": adv_name,
					"additional_salary": add_sal.name,
					"employee_name": adv.employee_name,
					"amount": flt(add_sal.amount, 2),
				}
			)
		except Exception as exc:
			frappe.db.rollback(save_point=sp)
			errors.append({"name": adv_name, "error": str(exc)})

	recalculated = _recalculate_draft_slips(affected_employees, target_date)
	return {"created": created, "recalculated": recalculated, "errors": errors}
