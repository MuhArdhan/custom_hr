"""Bulk payroll: run the native Payroll Entry for the chosen companies of one period, then submit their slips.

Each company still gets its own native Payroll Entry; this only saves opening one per company.
The dialog sends one company per request and shows the progress, including HRMS background queue state (>30 slips).
"""

import frappe
from frappe import _
from frappe.utils import cint, strip_html

from custom_hr.api.payroll_input import period_bounds

FREQUENCY = "Monthly"


def _require(ptype: str) -> None:
	if not frappe.has_permission("Payroll Entry", ptype):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def blocker(key: tuple, done: set | dict, account: str | None, cost_center: str | None) -> str | None:
	"""Why a company and payable account cannot get a Payroll Entry for the period, or None when it can."""
	if key in done:
		status = done.get(key) if isinstance(done, dict) else None
		if status == "Queued":
			return _("Queued in background")
		if status == "Failed":
			return _("Last run failed")
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
	done = {}
	for entry in frappe.get_all(
		"Payroll Entry",
		filters={"start_date": start, "end_date": end, "docstatus": ["<", 2]},
		fields=["company", "payroll_payable_account", "status"],
		order_by="creation asc",
	):
		done[(entry.company, entry.payroll_payable_account)] = entry.status
	companies = frappe.get_all(
		"Company",
		filters={"name": ["in", [row.company for row in rows] or [""]]},
		fields=["name", "cost_center", "default_currency"],
	)
	by_name = {company.name: company for company in companies}
	for row in rows:
		company = by_name.get(row.company) or frappe._dict()
		key = (row.company, row.account)
		status = done.get(key)
		row.name = f"{row.company}\n{row.account or ''}"
		row.cost_center, row.currency = company.cost_center, company.default_currency
		row.reason = blocker(key, done, row.account, row.cost_center)
		row.queued = status == "Queued"
		row.failed = status == "Failed"
		row.done = key in done and not row.queued and not row.failed
	return rows


def _submit_targets(start, end) -> list[dict]:
	rows = frappe.db.sql(
		"""
		SELECT pe.name, pe.company, pe.payroll_payable_account AS account,
			pe.status,
			COUNT(ss.name) AS slips, COALESCE(SUM(ss.net_pay), 0) AS net_pay
		FROM `tabPayroll Entry` pe
		LEFT JOIN `tabSalary Slip` ss ON ss.payroll_entry = pe.name AND ss.docstatus = 0
		WHERE pe.docstatus = 1 AND pe.start_date = %(start)s AND pe.end_date = %(end)s
		GROUP BY pe.name, pe.company, pe.payroll_payable_account, pe.status
		HAVING COUNT(ss.name) > 0 OR pe.status = 'Queued'
		ORDER BY pe.company
		""",
		{"start": start, "end": end},
		as_dict=True,
	)
	for row in rows:
		row.queued = row.status == "Queued"
		row.reason = _("Queued in background") if row.queued else None
	return rows


@frappe.whitelist(methods=["GET"])
def get_bulk_targets(month: str, mode: str) -> list[dict]:
	start, end = period_bounds(month)
	if mode == "create":
		_require("create")
		return _create_targets(start, end)
	_require("submit")
	return _submit_targets(start, end)


@frappe.whitelist(methods=["GET"])
def get_preflight(month: str) -> dict:
	"""Audit period readiness before running bulk payroll: SSA coverage, accounts, pending approvals, queue state."""
	_require("read")
	start, end = period_bounds(month)
	params = {"start": start, "end": end}

	missing_ssa = frappe.db.sql(
		"""
		SELECT e.name, e.employee_name, e.company, e.department, e.date_of_joining
		FROM `tabEmployee` e
		WHERE (e.status = 'Active' OR e.relieving_date >= %(start)s)
			AND (e.date_of_joining IS NULL OR e.date_of_joining <= %(end)s)
			AND NOT EXISTS (
				SELECT 1 FROM `tabSalary Structure Assignment` ssa
				WHERE ssa.employee = e.name AND ssa.docstatus = 1 AND ssa.from_date <= %(end)s
			)
		ORDER BY e.company, e.employee_name
		""",
		params,
		as_dict=True,
	)

	missing_payable = frappe.db.sql(
		"""
		SELECT ssa.name, ssa.employee, e.employee_name, ssa.company
		FROM `tabSalary Structure Assignment` ssa
		JOIN `tabEmployee` e ON e.name = ssa.employee
		WHERE ssa.docstatus = 1 AND ssa.from_date <= %(end)s
			AND (e.status = 'Active' OR e.relieving_date >= %(start)s)
			AND (ssa.payroll_payable_account IS NULL OR ssa.payroll_payable_account = '')
		ORDER BY ssa.company, e.employee_name
		""",
		params,
		as_dict=True,
	)

	active_companies = sorted(
		{
			c
			for c in frappe.db.sql_list(
				"""
				SELECT DISTINCT company FROM `tabEmployee`
				WHERE company IS NOT NULL AND company != ''
					AND (status = 'Active' OR relieving_date >= %(start)s)
					AND (date_of_joining IS NULL OR date_of_joining <= %(end)s)
				""",
				params,
			)
		}
	)
	default_payable_num = (
		frappe.db.get_single_value("Payroll Settings", "default_payroll_payable_account_number") or ""
	).strip()
	payable_companies = (
		set(
			frappe.get_all(
				"Account",
				filters={"account_number": default_payable_num, "company": ["in", active_companies or [""]], "is_group": 0},
				pluck="company",
			)
		)
		if default_payable_num and active_companies
		else set(active_companies)
	)
	cost_center_by_company = {
		c.name: c.cost_cente
		for c in frappe.get_all("Company", filters={"name": ["in", active_companies or [""]]}, fields=["name", "cost_center"])
	}
	company_issues = []
	for company in active_companies:
		no_cc = not cost_center_by_company.get(company)
		no_acc = bool(default_payable_num) and company not in payable_companies
		if no_cc or no_acc:
			company_issues.append(
				{
					"company": company,
					"missing_cost_center": no_cc,
					"missing_default_payable": no_acc,
					"default_payable_number": default_payable_num,
				}
			)

	pending_overtime = frappe.get_all(
		"Overtime Request",
		filters={"date": ["between", [start, end]], "status": ["not in", ["Disetujui", "Ditolak"]]},
		fields=["name", "company", "date", "status", "planned_hours"],
		order_by="date asc, company asc",
	)
	pending_leave = frappe.get_all(
		"Leave Application",
		filters={"docstatus": 0, "status": "Open", "from_date": ["<=", end], "to_date": [">=", start]},
		fields=["name", "employee", "employee_name", "company", "leave_type", "from_date", "to_date"],
		order_by="from_date asc, company asc",
	)

	ter_enabled = bool(cint(frappe.db.get_single_value("Payroll Settings", "enable_pph21_ter")))
	ter_companies = (
		frappe.get_all("HRM TER Company", filters={"parent": "Payroll Settings"}, pluck="company")
		if ter_enabled
		else []
	)
	ter_filter_sql = "AND e.company IN %(ter_companies)s" if (ter_enabled and ter_companies) else ""
	ter_params = {**params, "ter_companies": tuple(ter_companies) or ("",)}
	ter_gaps = frappe.db.sql(
		f"""
		SELECT e.name, e.employee_name, e.company,
			(e.nik IS NULL OR e.nik = '') AS missing_nik,
			(e.marital_status IS NULL OR e.marital_status = '') AS missing_marital
		FROM `tabEmployee` e
		WHERE (e.status = 'Active' OR e.relieving_date >= %(start)s)
			AND (e.date_of_joining IS NULL OR e.date_of_joining <= %(end)s)
			{ter_filter_sql}
			AND ((e.nik IS NULL OR e.nik = '') OR (e.marital_status IS NULL OR e.marital_status = ''))
		ORDER BY e.company, e.employee_name
		""",
		ter_params,
		as_dict=True,
	)

	entry_issues = frappe.get_all(
		"Payroll Entry",
		filters={"start_date": start, "end_date": end, "docstatus": 1, "status": ["in", ["Queued", "Failed"]]},
		fields=["name", "company", "status", "error_message"],
		order_by="company asc",
	)
	for entry in entry_issues:
		entry.error_message = strip_html(entry.error_message or "")

	blockers_count = len(missing_ssa) + len(missing_payable) + len(company_issues) + sum(1 for e in entry_issues if e.status == "Failed")
	warnings_count = len(pending_overtime) + len(pending_leave) + (len(ter_gaps) if ter_enabled else 0) + sum(1 for e in entry_issues if e.status == "Queued")

	return {
		"start_date": str(start),
		"end_date": str(end),
		"ready": blockers_count == 0,
		"blockers_count": blockers_count,
		"warnings_count": warnings_count,
		"missing_ssa": missing_ssa,
		"missing_payable": missing_payable,
		"company_issues": company_issues,
		"pending_overtime": pending_overtime,
		"pending_leave": pending_leave,
		"ter_enabled": ter_enabled,
		"ter_gaps": ter_gaps if ter_enabled else [],
		"ter_gaps_count": len(ter_gaps),
		"entry_issues": entry_issues,
	}


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
	if not row or row.queued:
		return (row and row.reason) or _("No draft salary slips")
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
	# above 30 employees HRMS queues slip creation in the background (status becomes Queued)
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
