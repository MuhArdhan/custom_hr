# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from custom_hr.api.overtime_pay import collect_month


def execute(filters=None):
	filters = filters or {}
	result = collect_month(filters.get("bulan"))
	rows = result["rows"]

	columns = [
		{"fieldname": "employee", "label": _("Karyawan"), "fieldtype": "Link", "options": "Employee", "width": 110},
		{"fieldname": "employee_name", "label": _("Nama"), "fieldtype": "Data", "width": 170},
		{"fieldname": "department", "label": _("Departemen"), "fieldtype": "Link", "options": "Department", "width": 150},
		{"fieldname": "days", "label": _("Hari"), "fieldtype": "Int", "width": 60},
		{"fieldname": "total_hours", "label": _("Total Jam"), "fieldtype": "Float", "precision": 2, "width": 90},
		{"fieldname": "wage_base", "label": _("Upah Sebulan"), "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "hourly_rate", "label": _("Upah / Jam"), "fieldtype": "Currency", "options": "currency", "width": 110},
		{"fieldname": "amount", "label": _("Upah Lembur"), "fieldtype": "Currency", "options": "currency", "width": 140},
	]

	total_hours = sum(row["total_hours"] for row in rows)
	total_amount = sum(row["amount"] for row in rows)
	report_summary = [
		{"label": _("Total Jam Lembur"), "value": total_hours, "indicator": "Blue"},
		{
			"label": _("Total Upah Lembur"),
			"value": total_amount,
			"datatype": "Currency",
			"currency": "IDR",
			"indicator": "Green",
		},
	]

	if rows:
		rows = [dict(row, currency="IDR") for row in rows]
		rows.append(
			{
				"employee_name": _("Total"),
				"days": "",
				"total_hours": total_hours,
				"wage_base": "",
				"hourly_rate": "",
				"amount": total_amount,
				"currency": "IDR",
			}
		)

	return columns, rows, None, None, report_summary
