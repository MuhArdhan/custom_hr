"""Bulk payroll: run the native Payroll Entry for the chosen companies of one period, then submit their slips.

Each company still gets its own native Payroll Entry; this only saves opening one per company.
The dialog sends one company per request and shows the progress.
"""

import frappe
from frappe import _
from frappe.utils import strip_html

from custom_hr.api.payroll_input import period_bounds

FREQUENCY = "Monthly"


def _require(ptype: str) -> None:
	if not frappe.has_permission("Payroll Entry", ptype):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def blocker(key: tuple, done: set, account: str | None, cost_center: str | None) -> str | None:
	"""Why a company and payable account cannot get a Payroll Entry for the period, or None when it can."""
	if key in done:
		return _("Already created")
	if not account:
		return _("No payroll payable account on the Salary Structure Assignment")
	if not cost_center:
		return _("The company has no default Cost Center")
	return None


def _create_targets(start, end) -> list[dict]:
	"""One target per company and payable account: the native Payroll Entry only takes employees of one account."""
	rows = frappe.db.sql(
		"""
		SELECT ssa.company, ssa.payroll_payable_account AS account, COUNT(DISTINCT ssa.employee) AS employees
		FROM `tabSalary Structure Assignment` ssa
		JOIN `tabEmployee` emp ON emp.name = ssa.employee
		WHERE ssa.docstatus = 1 AND ssa.from_date <= %(end)s
			AND (emp.status = 'Active' OR emp.relieving_date >= %(start)s)
		GROUP BY ssa.company, ssa.payroll_payable_account
		ORDER BY ssa.company, ssa.payroll_payable_account
		""",
		{"start": start, "end": end},
		as_dict=True,
	)
	done = {
		(entry.company, entry.payroll_payable_account)
		for entry in frappe.get_all(
			"Payroll Entry",
			filters={"start_date": start, "end_date": end, "docstatus": ["<", 2]},
			fields=["company", "payroll_payable_account"],
		)
	}
	companies = frappe.get_all("Company", filters={"name": ["in", [row.company for row in rows] or [""]]}, fields=["name", "cost_center", "default_currency"])
	by_name = {company.name: company for company in companies}
	for row in rows:
		company = by_name.get(row.company) or frappe._dict()
		row.name = f"{row.company}\n{row.account or ''}"
		row.cost_center, row.currency = company.cost_center, company.default_currency
		row.reason = blocker((row.company, row.account), done, row.account, row.cost_center)
		row.done = (row.company, row.account) in done
	return rows


def _submit_targets(start, end) -> list[dict]:
	return frappe.db.sql(
		"""
		SELECT pe.name, pe.company, pe.payroll_payable_account AS account, COUNT(ss.name) AS slips, SUM(ss.net_pay) AS net_pay
		FROM `tabPayroll Entry` pe
		JOIN `tabSalary Slip` ss ON ss.payroll_entry = pe.name AND ss.docstatus = 0
		WHERE pe.docstatus = 1 AND pe.start_date = %(start)s AND pe.end_date = %(end)s
		GROUP BY pe.name, pe.company, pe.payroll_payable_account
		ORDER BY pe.company
		""",
		{"start": start, "end": end},
		as_dict=True,
	)


@frappe.whitelist(methods=["GET"])
def get_bulk_targets(month: str, mode: str) -> list[dict]:
	start, end = period_bounds(month)
	if mode == "create":
		_require("create")
		return _create_targets(start, end)
	_require("submit")
	return _submit_targets(start, end)


@frappe.whitelist(methods=["POST"])
def create_payroll_entry(month: str, target: str) -> str | None:
	"""Create and submit one Payroll Entry, which makes its draft slips. Returns why it failed, or None."""
	_require("create")
	_require("submit")
	start, end = period_bounds(month)
	# re-checked here: the dialog may be stale, and a target already run must not get a second entry
	row = next((row for row in _create_targets(start, end) if row.name == target), None)
	if not row or row.reason:
		return (row and row.reason) or _("Not found in this period")
	return _run(row.company, lambda: _create(row, start, end))


@frappe.whitelist(methods=["POST"])
def submit_payroll_entry(month: str, target: str) -> str | None:
	"""Submit the draft slips of one Payroll Entry of the period. Returns why it failed, or None."""
	_require("submit")
	start, end = period_bounds(month)
	row = next((row for row in _submit_targets(start, end) if row.name == target), None)
	if not row:
		return _("No draft salary slips")
	return _run(row.company, lambda: _submit(row.name))


def _create(row, start, end) -> str:
	entry = frappe.get_doc(
		{
			"doctype": "Payroll Entry",
			"company": row.company,
			"posting_date": end,
			"payroll_frequency": FREQUENCY,
			"start_date": start,
			"end_date": end,
			"currency": row.currency,
			"exchange_rate": 1,
			"payroll_payable_account": row.account,
			"cost_center": row.cost_center,
		}
	)
	entry.insert()  # first, as the form does: the employee filter reads defaults set on insert
	entry.fill_employee_details()
	# shortcut: above 30 employees native queues the slips in the background, fine while companies stay small
	entry.submit()
	return entry.name


def _submit(name: str) -> str:
	# native: skips negative net pay and books the accrual journal; queued on its own above 30 slips
	frappe.get_doc("Payroll Entry", name).submit_salary_slips()
	return name


def _run(company: str, action) -> str | None:
	"""Run one target; on failure undo it and return the reason instead of raising, so the dialog moves on."""
	try:
		name = action() or ""
		frappe.db.commit()  # nosemgrep: the dialog runs targets one per request, each stands on its own
		error = name and frappe.db.get_value("Payroll Entry", name, ["status", "error_message"], as_dict=True)
		# native slip creation and submission catch their own errors and mark the entry Failed
		return strip_html(error.error_message or _("Failed")) if error and error.status == "Failed" else None
	except Exception as exc:
		frappe.db.rollback()
		frappe.log_error(title=f"Payroll massal: {company}")
		return strip_html(str(exc)) or exc.__class__.__name__
	finally:
		frappe.clear_messages()  # the dialog reports every target at the end, not one popup each
