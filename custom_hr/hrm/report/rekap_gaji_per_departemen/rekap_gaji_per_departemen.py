# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Rekap biaya gaji per departemen dari Salary Slip submitted.

Kolom komponen saat ini tetap: Basic, Tunjangan Tetap, Lembur (sesuai
pilot pabrik/gudang); tambahkan komponen saat outlet menyusul.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate

COMPONENTS = {
	"basic": "Basic",
	"tunjangan": "Tunjangan Tetap",
	"lembur": "Lembur",
}
NO_DEPARTMENT = "(tanpa departemen)"


def execute(filters=None):
	filters = filters or {}
	from_date = getdate(filters.get("from_date") or get_first_day(getdate()))
	to_date = getdate(filters.get("to_date") or get_last_day(getdate()))
	company = filters.get("company")

	columns = [
		{"fieldname": "department", "label": _("Departemen"), "fieldtype": "Data", "width": 220},
		{"fieldname": "employees", "label": _("Karyawan"), "fieldtype": "Int", "width": 90},
		{"fieldname": "basic", "label": _("Pokok"), "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "tunjangan", "label": _("Tunjangan Tetap"), "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "lembur", "label": _("Lembur"), "fieldtype": "Currency", "options": "currency", "width": 120},
		{"fieldname": "gross", "label": _("Total Bruto"), "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "deduction", "label": _("Potongan"), "fieldtype": "Currency", "options": "currency", "width": 120},
		{"fieldname": "net", "label": _("Dibayarkan"), "fieldtype": "Currency", "options": "currency", "width": 130},
	]

	params = {"from_date": from_date, "to_date": to_date}
	company_condition = ""
	if company:
		company_condition = "AND ss.company = %(company)s"
		params["company"] = company

	slips = frappe.db.sql(
		f"""
		SELECT ss.name, ss.employee, ss.gross_pay, ss.total_deduction, ss.net_pay,
			COALESCE(e.department, '') AS department
		FROM `tabSalary Slip` ss
		JOIN tabEmployee e ON e.name = ss.employee
		WHERE ss.docstatus = 1
			AND ss.start_date >= %(from_date)s
			AND ss.end_date <= %(to_date)s
			{company_condition}
		""",
		params,
		as_dict=True,
	)
	if not slips:
		return columns, [], None, None, []

	earnings = frappe.db.sql(
		"""
		SELECT sd.parent, sd.salary_component, SUM(sd.amount) AS amount
		FROM `tabSalary Detail` sd
		WHERE sd.parent IN %(parents)s
			AND sd.parentfield = 'earnings'
			AND sd.salary_component IN %(components)s
		GROUP BY sd.parent, sd.salary_component
		""",
		{
			"parents": tuple(slip.name for slip in slips),
			"components": tuple(COMPONENTS.values()),
		},
		as_dict=True,
	)
	earn_map = {}
	for row in earnings:
		earn_map.setdefault(row.parent, {})[row.salary_component] = flt(row.amount)

	group = {}
	for slip in slips:
		key = slip.department or NO_DEPARTMENT
		bucket = group.setdefault(
			key,
			{"employees": 0, "basic": 0.0, "tunjangan": 0.0, "lembur": 0.0, "gross": 0.0, "deduction": 0.0, "net": 0.0},
		)
		bucket["employees"] += 1
		slip_earnings = earn_map.get(slip.name, {})
		for field, component in COMPONENTS.items():
			bucket[field] += slip_earnings.get(component, 0)
		bucket["gross"] += flt(slip.gross_pay)
		bucket["deduction"] += flt(slip.total_deduction)
		bucket["net"] += flt(slip.net_pay)

	rows = []
	for department in sorted(group):
		rows.append(dict(group[department], department=department, currency="IDR"))

	total = {"employees": 0, "basic": 0.0, "tunjangan": 0.0, "lembur": 0.0, "gross": 0.0, "deduction": 0.0, "net": 0.0}
	for row in rows:
		for field in total:
			total[field] += row[field]
	rows.append(dict(total, department=_("Total"), currency="IDR"))

	return columns, rows, None, None, []
