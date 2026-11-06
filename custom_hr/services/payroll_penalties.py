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
	settings = frappe.get_cached_doc("HRM Payroll Settings")
	doc.jumlah_telat = sum(day.late_entry for day in days)
	doc.jumlah_pulang_cepat = sum(day.early_exit for day in days)
	doc.jumlah_tidak_out = sum(day.missing_checkout for day in days)
	doc.tarif_telat = settings.potongan_telat
	doc.tarif_pulang_cepat = settings.potongan_pulang_cepat
	doc.tarif_tidak_out = settings.potongan_tidak_out
