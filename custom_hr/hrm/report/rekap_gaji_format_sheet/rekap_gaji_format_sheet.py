"""The slips of one Payroll Entry laid out like HR's salary sheet: one row per employee, the components in the
order of their Excel column in Payroll Settings (tab HRM, Cocokkan Gaji dengan Excel), so an export reads side
by side with the sheet."""

import frappe
from frappe import _
from frappe.utils import flt

from custom_hr.api.payroll_match import column_groups, nip_text


def execute(filters=None):
	entry = (filters or {}).get("payroll_entry")
	if not entry:
		return [], []
	frappe.has_permission("Payroll Entry", "read", entry, throw=True)
	groups = column_groups(frappe.get_cached_doc("Payroll Settings").match_columns, set())
	slips = frappe.db.sql(
		"""
		SELECT ss.name, ss.employee, ss.employee_name, emp.employee_number AS nip, ss.designation, ss.department,
			ss.jumlah_hadir, ss.jam_lembur, ss.gross_pay, ss.total_deduction, ss.net_pay, ss.status
		FROM `tabSalary Slip` ss JOIN `tabEmployee` emp ON emp.name = ss.employee
		WHERE ss.payroll_entry = %s AND ss.docstatus < 2
		ORDER BY ss.employee_name
		""",
		entry,
		as_dict=True,
	)
	amounts = {}
	if slips:
		for row in frappe.get_all("Salary Detail", filters={"parenttype": "Salary Slip", "parent": ["in", [s.name for s in slips]]}, fields=["parent", "salary_component", "amount"]):
			slip = amounts.setdefault(row.parent, {})
			slip[row.salary_component] = slip.get(row.salary_component, 0) + flt(row.amount)
	return columns(groups), sheet_rows(slips, amounts, groups)


def ordered(groups) -> list:
	"""Groups left to right as in the sheet: AL before AO+AQ before BF."""
	return sorted(groups, key=lambda g: g.indexes[0])


def columns(groups) -> list:
	money = {"fieldtype": "Currency", "options": "currency", "width": 120}
	return [
		{"fieldname": "nip", "label": _("NIP"), "fieldtype": "Data", "width": 90},
		{"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 120},
		{"fieldname": "employee_name", "label": _("Nama"), "fieldtype": "Data", "width": 180},
		{"fieldname": "designation", "label": _("Jabatan"), "fieldtype": "Data", "width": 130},
		{"fieldname": "department", "label": _("Departemen"), "fieldtype": "Data", "width": 130},
		{"fieldname": "jumlah_hadir", "label": _("Hadir"), "fieldtype": "Float", "width": 70},
		{"fieldname": "jam_lembur", "label": _("Jam Lembur"), "fieldtype": "Float", "width": 90},
		*[dict(money, fieldname=g.key, label=f"{g.key} · {' + '.join(g.components)}") for g in ordered(groups)],
		dict(money, fieldname="gross_pay", label=_("Total Pendapatan")),
		dict(money, fieldname="total_deduction", label=_("Total Potongan")),
		dict(money, fieldname="net_pay", label=_("Diterima")),
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 90},
	]


def sheet_rows(slips, amounts, groups) -> list:
	rows = []
	for slip in slips:
		row = dict(slip, nip=nip_text(slip.nip), currency="IDR")
		row.pop("name")
		got = amounts.get(slip.name, {})
		for g in groups:
			row[g.key] = flt(sum(flt(got.get(c)) for c in g.components), 2)
		rows.append(row)
	return rows
