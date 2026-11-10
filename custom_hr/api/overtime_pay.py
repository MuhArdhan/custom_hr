# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Kalkulasi upah lembur PP 35/2021 (hari kerja) dari pengajuan disetujui.

Basis upah sebulan = komponen di HRM Payroll Settings: yang ditandai
"Dari Base SSA" memakai Base Salary Structure Assignment, sisanya memakai
amount baris struktur (formula belum didukung). Upah sejam = basis / 173.

Tarif hari kerja PP 35/2021: jam ke-1 x1.5, jam ke-2 dst x2.
Jam dibayar = min(aktual absensi, jam rencana pengajuan yang disetujui).

Hasil dikonversi menjadi draft Additional Salary per karyawan per bulan
(komponen lembur) supaya ikut payroll setelah disubmit HRD.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate

from custom_hr.api.roster import HR_ROLES

TIER1_HOURS = 1.0
TIER1_FACTOR = 1.5
TIER2_FACTOR = 2.0


def _require_hr():
	if not set(HR_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Hanya HR yang dapat menjalankan aksi ini"), frappe.PermissionError)


def _month_bounds(bulan=None):
	base = getdate(bulan) if bulan else getdate()
	return get_first_day(base), get_last_day(base)


def tiered_amount(hours, hourly_rate):
	"""PP 35/2021 hari kerja: jam ke-1 x1.5, jam berikutnya x2."""
	hours = flt(hours, 2)
	first = min(hours, TIER1_HOURS)
	rest = max(hours - TIER1_HOURS, 0)
	return flt(hourly_rate * (first * TIER1_FACTOR + rest * TIER2_FACTOR), 2)


def _wage_base(employee, on_date, settings):
	ssa = frappe.get_all(
		"Salary Structure Assignment",
		filters={"employee": employee, "docstatus": 1, "from_date": ["<=", on_date]},
		fields=["base", "salary_structure"],
		order_by="from_date desc",
		limit=1,
		ignore_permissions=True,
	)
	if not ssa:
		return None

	components = [row.salary_component for row in settings.wage_base_components]
	structure_amounts = {}
	if components:
		structure_amounts = {
			row.salary_component: flt(row.amount)
			for row in frappe.get_all(
				"Salary Detail",
				filters={
					"parent": ssa[0].salary_structure,
					"parentfield": "earnings",
					"salary_component": ["in", components],
				},
				fields=["salary_component", "amount"],
				ignore_permissions=True,
			)
		}

	base = 0.0
	for row in settings.wage_base_components:
		if row.use_ssa_base:
			base += flt(ssa[0].base)
		else:
			base += structure_amounts.get(row.salary_component, 0)

	return base


def paid_overtime(from_date, to_date, employee=None) -> dict:
	"""{(employee, date): {hours, overtime_type}}; hours = min(actual overtime on the attendance, approved planned hours)."""
	requests = frappe.get_all(
		"Overtime Request",
		filters={"status": ["!=", "Ditolak"], "date": ["between", [from_date, to_date]]},
		fields=["name", "date", "planned_hours", "status", "overtime_type"],
		ignore_permissions=True,
	)
	planned = {}
	if requests:
		req_map = {r.name: r for r in requests}
		row_filters = {"parent": ["in", list(req_map)]}
		if employee:
			row_filters["employee"] = employee
		for row in frappe.get_all(
			"Overtime Request Employee",
			filters=row_filters,
			fields=["parent", "employee", "approval_state"],
			ignore_permissions=True,
		):
			req = req_map[row.parent]
			if (row.get("approval_state") or req.status) != "Disetujui":
				continue
			key = (row.employee, getdate(req.date))
			cap = flt(req.planned_hours)
			if key not in planned or cap < planned[key][0]:
				planned[key] = (cap, req.overtime_type)
	if not planned:
		return {}

	attendance = frappe.get_all(
		"Attendance",
		filters={
			"employee": ["in", sorted({e for e, _ in planned})],
			"attendance_date": ["between", [from_date, to_date]],
			"docstatus": 1,
		},
		fields=["employee", "attendance_date", "actual_overtime_duration"],
		ignore_permissions=True,
	)
	actual = {
		(a.employee, getdate(a.attendance_date)): flt(a.actual_overtime_duration) for a in attendance
	}
	paid = {
		key: frappe._dict(hours=min(actual.get(key, 0), cap), overtime_type=overtime_type)
		for key, (cap, overtime_type) in planned.items()
	}
	return {key: row for key, row in paid.items() if row.hours > 0}


def overtime_multiplier(overtime_type, holiday) -> float:
	"""Overtime Type multiplier for the day: weekly off, public holiday, or a normal day."""
	if holiday and holiday.weekly_off and overtime_type.applicable_for_weekend:
		return flt(overtime_type.weekend_multiplier) or 1
	if holiday and not holiday.weekly_off and overtime_type.applicable_for_public_holiday:
		return flt(overtime_type.public_holiday_multiplier) or 1
	return flt(overtime_type.standard_multiplier) or 1


def overtime_pay(employee, overtime: dict, from_date, to_date) -> float:
	"""Paid hours x the Overtime Type's fixed hourly rate x its day multiplier, summed."""
	if not overtime:
		return 0.0
	from hrms.utils.holiday_list import get_holiday_dates_between_range

	holidays = {
		getdate(row.holiday_date): row
		for row in get_holiday_dates_between_range(
			employee, from_date, to_date, raise_exception_for_holiday_list=False, as_dict=True
		)
	}
	total = 0.0
	for (_employee, date), row in overtime.items():
		overtime_type = frappe.get_cached_doc("Overtime Type", row.overtime_type)
		rate = flt(overtime_type.hourly_rate)
		# shortcut: Salary Component Based and the tiered PP 35 rate are not paid here yet; add them when HR adopts them
		if overtime_type.overtime_calculation_method != "Fixed Hourly Rate" or rate <= 0:
			frappe.throw(
				_(
					"Overtime Type {0} belum memakai Fixed Hourly Rate dengan Hourly Rate terisi, jadi lembur {1} tanggal {2} belum bisa dibayar."
				).format(overtime_type.name, employee, frappe.format(date, "Date"))
			)
		total += row.hours * rate * overtime_multiplier(overtime_type, holidays.get(date))
	return flt(total, 2)


def collect_month(bulan=None):
	"""Satu baris per karyawan: jam lembur terutang + rincian upahnya."""
	settings = frappe.get_cached_doc("HRM Payroll Settings")
	from_date, to_date = _month_bounds(bulan)
	divisor = flt(settings.overtime_hourly_divisor) or 173

	result = {
		"from_date": from_date,
		"to_date": to_date,
		"rows": [],
		"overtime_salary_component": settings.overtime_salary_component,
	}
	paid = paid_overtime(from_date, to_date)
	if not paid:
		return result

	per_employee = {}
	for (employee, date), row in paid.items():
		hours = row.hours
		base = _wage_base(employee, date, settings)
		if base is None:
			continue
		entry = per_employee.setdefault(
			employee, {"wage_base": base, "hours": 0.0, "amount": 0.0, "days": 0}
		)
		entry["wage_base"] = base
		entry["hours"] += hours
		entry["amount"] += tiered_amount(hours, base / divisor)
		entry["days"] += 1

	for employee, entry in sorted(per_employee.items()):
		info = frappe.db.get_value(
			"Employee", employee, ["employee_name", "department"], as_dict=True
		)
		result["rows"].append(
			{
				"employee": employee,
				"employee_name": info.employee_name,
				"department": info.department,
				"days": entry["days"],
				"total_hours": flt(entry["hours"], 2),
				"wage_base": flt(entry["wage_base"], 2),
				"hourly_rate": flt(entry["wage_base"] / divisor, 2),
				"amount": flt(entry["amount"], 2),
			}
		)
	return result


@frappe.whitelist()
def preview_overtime_pay(bulan=None):
	_require_hr()
	return collect_month(bulan)["rows"]


@frappe.whitelist()
def generate_overtime_salary(bulan=None):
	"""Draft Additional Salary per karyawan; draft lama bulan yang sama
	diganti, yang sudah submitted dilewati."""
	_require_hr()
	result = collect_month(bulan)
	component = result["overtime_salary_component"]
	if not component:
		frappe.throw(_("Set komponen upah lembur di HRM Payroll Settings"))

	created, skipped = [], []
	for row in result["rows"]:
		if row["amount"] <= 0:
			continue
		period = {
			"employee": row["employee"],
			"salary_component": component,
			"payroll_date": ["between", [result["from_date"], result["to_date"]]],
		}
		if frappe.db.exists("Additional Salary", {**period, "docstatus": 1}):
			skipped.append(row["employee_name"])
			continue
		for name in frappe.get_all(
			"Additional Salary",
			filters={**period, "docstatus": 0},
			pluck="name",
			ignore_permissions=True,
		):
			frappe.delete_doc("Additional Salary", name, ignore_permissions=True)

		doc = frappe.new_doc("Additional Salary")
		doc.employee = row["employee"]
		doc.salary_component = component
		doc.amount = row["amount"]
		doc.payroll_date = result["to_date"]
		doc.overwrite_salary_structure_amount = 1
		doc.insert(ignore_permissions=True)
		created.append(doc.name)

	return {"created": created, "skipped": skipped}
