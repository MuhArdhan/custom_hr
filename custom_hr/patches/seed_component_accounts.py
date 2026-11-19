"""Akun Komponen Gaji starts from the accounts HR already set on each Salary Component, one row per company.

Nothing changes on the first sync: the table only restates them. Rows are inserted directly because the
Payroll Settings table field is a fixture, made after patches run. An account without a number is skipped.
"""

import frappe

CHILD, PARENT, FIELD = "HRM Component Account", "Payroll Settings", "component_accounts"


def execute():
	if frappe.db.count(CHILD, {"parenttype": PARENT}):
		return
	rows = frappe.db.sql(
		"""SELECT sca.parent AS salary_component, sca.company, acc.account_number
		FROM `tabSalary Component Account` sca JOIN `tabAccount` acc ON acc.name = sca.account
		WHERE sca.parenttype = 'Salary Component' AND IFNULL(acc.account_number, '') != ''
		ORDER BY sca.company, sca.parent""",
		as_dict=True,
	)
	for idx, row in enumerate(rows, start=1):
		doc = frappe.get_doc(
			{
				"doctype": CHILD,
				"parent": PARENT,
				"parenttype": PARENT,
				"parentfield": FIELD,
				"idx": idx,
				"salary_component": row.salary_component,
				"for_company": row.company,
				"account_number": row.account_number,
			}
		)
		doc.set_new_name()
		doc.db_insert()
