"""Salary Component accounts kept from one table in Payroll Settings (tab HRM).

A row names an account number; every company gets its own account with that number. The table wins: a
component it lists has its company accounts overwritten, a component it does not list is left alone.
"""

import frappe
from frappe import _

SETTINGS = "Payroll Settings"


def plan(rows, companies, accounts) -> tuple[dict, list]:
	"""-> ({component: {company: account}}, [(component, company, number) with no such account]).

	accounts: {(company, account number): account name}. A company's own row beats the row without a company.
	"""
	numbers = {}
	for row in rows:
		numbers.setdefault(row.salary_component, {})[row.for_company or ""] = (row.account_number or "").strip()
	wanted, missing = {}, []
	for component, by_company in numbers.items():
		for company in companies:
			number = by_company.get(company) or by_company.get("")
			if not number:
				continue
			account = accounts.get((company, number))
			if account:
				wanted.setdefault(component, {})[company] = account
			else:
				missing.append((component, company, number))
	return wanted, missing


def sync(rows, companies=None) -> list:
	"""Writes the planned accounts into each Salary Component; returns what could not be found."""
	if not rows:
		return []
	companies = companies or frappe.get_all("Company", pluck="name")
	numbers = {(row.account_number or "").strip() for row in rows}
	accounts = {
		(a.company, a.account_number): a.name
		for a in frappe.get_all(
			"Account",
			filters={"account_number": ["in", list(numbers)], "company": ["in", companies], "is_group": 0},
			fields=["name", "company", "account_number"],
		)
	}
	wanted, missing = plan(rows, companies, accounts)
	for component, by_company in wanted.items():
		doc = frappe.get_doc("Salary Component", component)
		existing = {row.company: row for row in doc.accounts}
		changed = False
		for company, account in by_company.items():
			row = existing.get(company)
			if row is None:
				doc.append("accounts", {"company": company, "account": account})
				changed = True
			elif row.account != account:
				row.account = account
				changed = True
		if changed:
			doc.save(ignore_permissions=True)
	return missing


def on_settings_update(doc, method=None):
	"""Payroll Settings on_update: every company follows the table; the ones lacking a number are reported."""
	missing = sync(doc.get("component_accounts"))
	if missing:
		by_number = {}
		for _component, company, number in missing:
			by_number.setdefault(number, set()).add(company)
		lines = [
			_("{0}: {1} company, mis. {2}").format(number, len(companies), ", ".join(sorted(companies)[:3]))
			for number, companies in sorted(by_number.items())
		]
		frappe.msgprint(
			_("Akun komponen tidak diisi untuk company yang tidak punya nomor akun ini:") + "<br>" + "<br>".join(lines),
			title=_("Akun Komponen Gaji"),
			indicator="orange",
		)


def on_company_update(doc, method=None):
	"""Company on_update: a new outlet gets its component accounts once its chart of accounts exists."""
	sync(frappe.get_cached_doc(SETTINGS).get("component_accounts"), [doc.name])
