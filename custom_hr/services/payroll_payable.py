"""Default Salary Structure Assignment payroll payable account resolved per company from Payroll Settings."""

import frappe

SETTINGS = "Payroll Settings"


def resolve_payable_account(company: str | None, account_number: str | None) -> str | None:
	"""Return the company's leaf Account matching account_number, or None if unavailable."""
	number = (account_number or "").strip()
	if not company or not number:
		return None
	return frappe.db.get_value(
		"Account",
		{"company": company, "account_number": number, "is_group": 0},
		"name",
	)


@frappe.whitelist()
def get_default_payable_account(company: str | None) -> str | None:
	if not company:
		return None
	number = frappe.db.get_single_value(SETTINGS, "default_payroll_payable_account_number")
	return resolve_payable_account(company, number)


def fill_payable_account(doc, method=None):
	"""Salary Structure Assignment before_validate: auto-fill payroll_payable_account when blank."""
	if doc.get("payroll_payable_account") or not doc.get("company"):
		return
	account = get_default_payable_account(doc.company)
	if account:
		doc.payroll_payable_account = account


def seed_default_payable_account_number():
	"""Seed default_payroll_payable_account_number once on Payroll Settings without overriding user edits."""
	if not frappe.db.exists("Custom Field", "Payroll Settings-default_payroll_payable_account_number"):
		return
	exists = frappe.db.sql(
		"SELECT 1 FROM `tabSingles` WHERE `doctype` = %s AND `field` = %s LIMIT 1",
		(SETTINGS, "default_payroll_payable_account_number"),
	)
	if not exists:
		frappe.db.set_single_value(SETTINGS, "default_payroll_payable_account_number", "2131.002")
