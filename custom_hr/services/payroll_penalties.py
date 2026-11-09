"""Late, early exit and missing checkout on the Salary Slip, for Salary Structure formulas to multiply."""

import frappe

COUNTED_STATUSES = ("Present", "Half Day", "Work From Home")


def fill_attendance_penalties(doc, method=None):
	"""before_validate: formulas cannot read Attendance. A submitted slip keeps the counts and rates it was paid on."""
	if doc.docstatus or not (doc.employee and doc.start_date and doc.end_date):
		return
	days = frappe.get_all(
		"Attendance",
		filters={
			"employee": doc.employee,
			"docstatus": 1,
			"status": ["in", COUNTED_STATUSES],
			"attendance_date": ["between", [doc.start_date, doc.end_date]],
		},
		fields=["late_entry", "early_exit", "missing_checkout"],
		ignore_permissions=True,
	)
	rate = rate_for(frappe.get_cached_doc("HRM Payroll Settings").attendance_penalty_rates, doc.company)
	doc.jumlah_telat = sum(day.late_entry for day in days)
	doc.jumlah_pulang_cepat = sum(day.early_exit for day in days)
	doc.jumlah_tidak_out = sum(day.missing_checkout for day in days)
	doc.tarif_telat = rate.get("potongan_telat") or 0
	doc.tarif_pulang_cepat = rate.get("potongan_pulang_cepat") or 0
	doc.tarif_tidak_out = rate.get("potongan_tidak_out") or 0


def rate_for(rows, company):
	"""The company's own row, else the row without a company, else no deduction."""
	by_company = {row.for_company or "": row for row in rows}
	return by_company.get(company) or by_company.get("") or {}
