"""Cocokkan Gaji: compare HR's salary sheet with the draft slips of one Payroll Entry, cell by cell.

The sheet is read in memory and never saved: it holds every employee's salary.
Columns come from HRM Payroll Settings by letter (the PH sheet's two-row headers put labels and values in
different columns). Taking the Excel value of a cell submits an overwriting Additional Salary for that
component, tagged with the Payroll Entry, and recalculates the slip.
"""

import base64
import io
import json
import re

import frappe
from frappe import _
from frappe.utils import flt
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

TOLERANCE = 1  # rupiah: the sheet rounds some amounts
HEADER_ROWS = 20  # the NIP header is searched in this many top rows
COLUMNS = re.compile(r"^[A-Z]{1,3}(\+[A-Z]{1,3})*$")


def column_groups(rows, period_input: set) -> list:
	"""Mapping rows -> one group per Excel column key; a key may list several columns and several components.

	Only a group of one component outside Input Additional Salary can take the Excel value: a combined
	amount cannot be split, and period input components have their own page.
	"""
	groups = {}
	for row in rows:
		key = re.sub(r"\s", "", row.excel_column or "").upper()
		if not COLUMNS.match(key):
			frappe.throw(_("Kolom Excel {0} tidak valid. Isi huruf kolom, mis. AY, atau AO+AQ untuk menjumlah.").format(row.excel_column or "''"))
		group = groups.setdefault(key, frappe._dict(key=key, indexes=[column_index_from_string(c) - 1 for c in key.split("+")], components=[]))
		group.components.append(row.salary_component)
	for group in groups.values():
		group.editable = len(group.components) == 1 and group.components[0] not in period_input
	return list(groups.values())


def nip_text(value) -> str:
	"""123456.0 (a number cell) and ' 123456 ' both -> '123456'."""
	if isinstance(value, float) and value.is_integer():
		value = int(value)
	return str(value).strip() if value is not None else ""


def read_sheet(rows, groups) -> tuple[dict, list]:
	"""{nip: {group key: amount}} from the row under the NIP header down to the first row without a NIP."""
	rows = iter(rows)
	for _row, header in zip(range(HEADER_ROWS), rows):
		nip_col = next((i for i, value in enumerate(header) if isinstance(value, str) and value.strip().upper() == "NIP"), None)
		if nip_col is not None:
			break
	else:
		frappe.throw(_("Kolom NIP tidak ditemukan di {0} baris teratas sheet.").format(HEADER_ROWS))

	amounts, duplicates = {}, []
	for row in rows:
		nip = nip_text(row[nip_col] if len(row) > nip_col else None)
		if not nip:
			break  # below the main table the PH sheet holds other tables
		if nip in amounts:
			duplicates.append(nip)
		amounts[nip] = {g.key: sum(row[i] for i in g.indexes if i < len(row) and isinstance(row[i], (int, float))) for g in groups}
	return amounts, duplicates


def compare_rows(sheet: dict, slips: list, groups: list) -> frappe._dict:
	"""Rows of the slips with at least one differing cell, plus who is only on one side."""
	rows, matched = [], 0
	for slip in slips:
		excel = sheet.get(slip.nip)
		if excel is None:
			continue
		matched += 1
		cells = {}
		for group in groups:
			system = flt(sum(flt(slip.amounts.get(component)) for component in group.components), 2)
			if abs(system - excel[group.key]) > TOLERANCE:
				cells[group.key] = {"system": system, "excel": excel[group.key]}
		if cells:
			rows.append(frappe._dict(slip=slip.name, employee=slip.employee, employee_name=slip.employee_name, nip=slip.nip, cells=cells))
	nips = {slip.nip for slip in slips}
	return frappe._dict(
		rows=rows,
		matched=matched,
		not_in_slips=sorted(nip for nip in sheet if nip not in nips),
		not_in_excel=[frappe._dict(employee=s.employee, employee_name=s.employee_name, nip=s.nip) for s in slips if s.nip not in sheet],
	)


def _entry(name: str):
	entry = frappe.get_doc("Payroll Entry", name)
	entry.check_permission("write")
	if not frappe.has_permission("Additional Salary", "submit"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if entry.docstatus != 1:
		frappe.throw(_("Payroll Entry belum disubmit, slip gajinya belum dibuat."))
	return entry


def _groups() -> list:
	rows = frappe.get_cached_doc("HRM Payroll Settings").match_columns
	if not rows:
		frappe.throw(_("Isi dulu tabel Kolom Cocokkan Gaji di HRM Payroll Settings."))
	return column_groups(rows, set(frappe.get_all("Salary Component", filters={"show_in_period_input": 1}, pluck="name")))


def _slips(entry) -> list:
	slips = frappe.db.sql(
		"""
		SELECT ss.name, ss.employee, ss.employee_name, emp.employee_number AS nip
		FROM `tabSalary Slip` ss JOIN `tabEmployee` emp ON emp.name = ss.employee
		WHERE ss.payroll_entry = %s AND ss.docstatus = 0
		ORDER BY ss.employee_name
		""",
		entry.name,
		as_dict=True,
	)
	amounts = {}
	if slips:
		for row in frappe.get_all("Salary Detail", filters={"parenttype": "Salary Slip", "parent": ["in", [s.name for s in slips]]}, fields=["parent", "salary_component", "amount"]):
			slip = amounts.setdefault(row.parent, {})
			slip[row.salary_component] = slip.get(row.salary_component, 0) + flt(row.amount)
	for slip in slips:
		slip.nip = nip_text(slip.nip)
		slip.amounts = amounts.get(slip.name, {})
	return slips


@frappe.whitelist(methods=["POST"])
def compare(payroll_entry: str, content: str, sheet: str | None = None) -> dict:
	"""content is the .xlsx as base64. Without a sheet name it returns the sheet names to pick from."""
	entry = _entry(payroll_entry)
	groups = _groups()
	try:
		book = load_workbook(io.BytesIO(base64.b64decode(content)), read_only=True, data_only=True)
	except Exception:
		frappe.throw(_("File tidak bisa dibaca sebagai Excel (.xlsx)."))
	try:
		if not sheet:
			return {"sheets": book.sheetnames}
		if sheet not in book.sheetnames:
			frappe.throw(_("Sheet {0} tidak ada di file.").format(sheet))
		amounts, duplicates = read_sheet(book[sheet].iter_rows(values_only=True), groups)
	finally:
		book.close()
	duplicates = sorted(set(duplicates))
	for nip in duplicates:  # which row is right is HR's call: both are left out and listed
		amounts.pop(nip)
	slips = _slips(entry)
	result = compare_rows(amounts, slips, groups)
	result.duplicates = duplicates
	labels = {g.key: " + ".join(g.components) for g in groups}
	result.columns = [{"key": g.key, "label": labels[g.key], "editable": g.editable, "component": g.components[0]} for g in groups]
	result.slips = len(slips)
	return result


@frappe.whitelist(methods=["POST"])
def apply(payroll_entry: str, changes: str | list) -> dict:
	"""Each change is {slip, column, amount}: the Excel amount compare returned for that cell.

	All or nothing, so a refused cell leaves every slip as it was.
	"""
	entry = _entry(payroll_entry)
	changes = json.loads(changes) if isinstance(changes, str) else changes
	editable = {g.key: g.components[0] for g in _groups() if g.editable}
	slips = {s.name: s for s in frappe.get_all("Salary Slip", filters={"payroll_entry": entry.name, "docstatus": 0}, fields=["name", "employee", "company", "end_date"])}
	touched, cancelled = set(), set()
	for change in changes:
		slip, component, amount = slips.get(change["slip"]), editable.get(change["column"]), flt(change.get("amount"))
		if not slip:
			frappe.throw(_("Slip {0} bukan slip draft Payroll Entry ini.").format(change["slip"]))
		if not component:
			frappe.throw(_("Kolom {0} tidak bisa diambil dari Excel.").format(change["column"]))
		if amount < 0:
			frappe.throw(_("Nilai Excel {0} untuk {1} minus.").format(component, slip.employee))
		# an earlier Pakai Excel of this entry is replaced, not stacked: native refuses two overwrites
		for name in frappe.get_all("Additional Salary", filters={"docstatus": 1, "employee": slip.employee, "salary_component": component, "ref_doctype": "Payroll Entry", "ref_docname": entry.name}, pluck="name"):
			frappe.get_doc("Additional Salary", name).cancel()
			cancelled.add(name)
		frappe.get_doc(
			{
				"doctype": "Additional Salary",
				"employee": slip.employee,
				"company": slip.company,
				"salary_component": component,
				"amount": amount,
				"payroll_date": slip.end_date,
				"overwrite_salary_structure_amount": 1,
				"ref_doctype": "Payroll Entry",
				"ref_docname": entry.name,
			}
		).submit()
		touched.add(slip.name)
	for name in touched:
		slip = frappe.get_doc("Salary Slip", name)
		for table in ("earnings", "deductions"):  # a row still linked to a cancelled one blocks the save
			slip.set(table, [row for row in slip.get(table) if row.additional_salary not in cancelled])
		slip.save()  # validate recalculates the components with the new Additional Salary
	return {"applied": len(changes), "slips": len(touched)}
