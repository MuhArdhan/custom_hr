"""Attendance counts, overtime hours, allowances and HR rates on the Salary Slip, for Salary Structure formulas to use."""

import frappe
from frappe.utils import cint, flt
from frappe.utils.nestedset import get_ancestors_of

from custom_hr.api.overtime_pay import overtime_pay, paid_overtime
from custom_hr.services.hourly_leave import izin_hours

COUNTED_STATUSES = ("Present", "Half Day", "Work From Home")
HALF_DAY = "Half Day"
ON_LEAVE = "On Leave"


def fill_attendance_penalties(doc, method=None):
	"""before_validate: formulas cannot read Attendance. A submitted slip keeps the counts and rates it was paid on."""
	if doc.docstatus or not (doc.employee and doc.start_date and doc.end_date):
		return
	days = frappe.get_all(
		"Attendance",
		filters={
			"employee": doc.employee,
			"docstatus": 1,
			"status": ["in", (*COUNTED_STATUSES, ON_LEAVE)],
			"attendance_date": ["between", [doc.start_date, doc.end_date]],
		},
		fields=["status", "late_entry", "early_exit", "missing_checkout", "shift", "leave_type"],
		ignore_permissions=True,
	)
	settings = frappe.get_cached_doc("Payroll Settings")
	rate = rate_for(settings.attendance_penalty_rates, doc.company)
	worked = [day for day in days if day.status in COUNTED_STATUSES]
	# leave earns meal and daily wage only when HR ticked its Leave Type
	paid_leave = [
		day
		for day in days
		if day.status == ON_LEAVE
		and day.leave_type
		and frappe.get_cached_value("Leave Type", day.leave_type, "dihitung_hadir")
	]
	doc.jumlah_hadir = sum(0.5 if day.status == HALF_DAY else 1 for day in worked) + len(paid_leave)
	# only the shifts HR listed in Payroll Settings (tab HRM) earn an allowance
	allowance = {row.shift_type: flt(row.tunjangan) for row in settings.shift_allowances}
	doc.tunjangan_shift = sum(allowance.get(day.shift, 0) for day in worked)
	# HR sets which designations earn an allowance, and how much, on the Designation itself
	for field in ("tunjangan_jabatan", "tunjangan_resiko"):
		setattr(doc, field, flt(frappe.get_cached_value("Designation", doc.designation, field)) if doc.designation else 0)
	# recorded Absent only: unmarked days (off days with a no-holiday list) are not alpha
	doc.jumlah_alpha = frappe.db.count(
		"Attendance",
		{"employee": doc.employee, "docstatus": 1, "status": "Absent", "attendance_date": ["between", [doc.start_date, doc.end_date]]},
	)
	doc.jam_izin = izin_hours(doc.employee, doc.start_date, doc.end_date)
	overtime = paid_overtime(doc.start_date, doc.end_date, doc.employee)
	doc.jam_lembur = sum(row.hours for row in overtime.values())
	doc.upah_lembur = overtime_pay(doc.employee, overtime, doc.start_date, doc.end_date)
	doc.jumlah_telat = sum(day.late_entry for day in worked)
	doc.jumlah_pulang_cepat = sum(day.early_exit for day in worked)
	doc.jumlah_tidak_out = sum(day.missing_checkout for day in worked)
	doc.tarif_telat = rate.get("potongan_telat") or 0
	doc.tarif_pulang_cepat = rate.get("potongan_pulang_cepat") or 0
	doc.tarif_tidak_out = rate.get("potongan_tidak_out") or 0
	daily = daily_rate(doc, settings)
	doc.tarif_uang_makan = daily.get("uang_makan") or 0
	doc.tarif_transport = daily.get("transport") or 0


def bpjs_values(doc, ssa) -> dict:
	"""Formula values: dasar_bpjs, and per HRM BPJS Rate row its kode = the capped base × persen.

	doc is a slip or the assignment's formula context: both carry employee, company and department.
	"""
	settings = frappe.get_cached_doc("Payroll Settings")
	if frappe.get_cached_value("Employee", doc.employee, "tidak_ikut_bpjs"):
		base = 0
	else:
		# Variable is the exception HR types; otherwise GP plus meal and transport for a fixed count of days
		daily = daily_rate(doc, settings)
		days = cint(daily.get("hari_bpjs"))
		base = flt(ssa.get("variable")) or flt(ssa.get("base")) + days * (flt(daily.get("uang_makan")) + flt(daily.get("transport")))
	values = {"dasar_bpjs": base}
	for row in settings.bpjs_rates:
		capped = min(base, flt(row.batas_atas)) if flt(row.batas_atas) else base
		values[row.kode.strip()] = flt(capped * flt(row.persen) / 100, 2)
	return values


def daily_rate(doc, settings):
	# a sub-department takes its parent's rate, e.g. a Jakarta team under Jakarta
	departments = [doc.department, *get_ancestors_of("Department", doc.department)] if doc.department else []
	return daily_rate_for(settings.daily_rates, doc.company, departments)


def rate_for(rows, company):
	"""The company's own row, else the row without a company, else no deduction."""
	by_company = {row.for_company or "": row for row in rows}
	return by_company.get(company) or by_company.get("") or {}


def daily_rate_for(rows, company, departments):
	"""departments: the slip's department, then its parents. Most specific row first, the empty row last."""
	by_place = {(row.for_company or "", row.for_department or ""): row for row in rows}
	places = [(company, d) for d in departments] + [(company, "")] + [("", d) for d in departments] + [("", "")]
	for place in places:
		if place in by_place:
			return by_place[place]
	return {}
