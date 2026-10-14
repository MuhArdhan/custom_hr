"""Payroll attendance summaries consumed by automatic native slip deductions.

Preview is read-only; enabled rules are applied by AttendancePayrollMixin.
No Additional Salary is created. Submitted snapshots remain historical.
"""

import hashlib
import json
from collections import defaultdict
from datetime import timedelta

import frappe
from frappe.utils import cint, date_diff, flt, get_datetime, get_timedelta, getdate, now_datetime

CATEGORIES = ("Alpha", "Izin", "Terlambat", "Tidak Absen IN", "Tidak Absen OUT")
SETTINGS = "HRM Attendance Payroll Settings"
RULE_FIELDS = ("category", "company", "salary_component", "unit", "hours_per_day", "enabled", "method", "rate", "divisor",
	"multiplier", "from_date", "to_date")
DETAIL_FIELDS = ("category", "salary_component", "quantity", "unit", "estimated_amount", "source_details")


def fingerprint(value):
	return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def applicable_rule(rules, category, day, company=None):
	matches = [row for row in rules if row.get("category") == category
		and (not company or not row.get("company") or row.get("company") == company)
		and getdate(row.get("from_date")) <= getdate(day)
		and (not row.get("to_date") or getdate(row.get("to_date")) >= getdate(day))]
	if company and any(row.get("company") for row in matches):
		matches = [row for row in matches if row.get("company") == company]
	if len(matches) > 1:
		frappe.throw("Aturan {0} bertumpang tindih. Periksa Setup Presensi Payroll.".format(category))
	return matches[0] if matches else None


def estimate_amount(quantity, rule, base, native_handled=False):
	if not rule or not cint(rule.get("enabled")) or native_handled:
		return 0.0
	if rule.get("method") == "Tarif Tetap":
		rate = flt(rule.get("rate"))
	elif rule.get("method") == "Base / Pembagi":
		if base is None or flt(rule.get("divisor")) <= 0:
			return 0.0
		rate = flt(base) / flt(rule.get("divisor"))
	else:
		return 0.0
	return flt(quantity * rate * flt(rule.get("multiplier", 1)), 2)


def event_quantity(event, rule):
	"""Convert only using measured lateness or an explicit HR day conversion."""
	unit = (rule or {}).get("unit") or "Hari"
	if unit == "Hari":
		return event["quantity"], unit
	if unit != "Jam":
		frappe.throw("Satuan aturan tidak valid.")
	if event["category"] == "Terlambat":
		return flt(event.get("minutes")) / 60, unit
	if event["category"] in ("Alpha", "Izin") and flt(rule.get("hours_per_day")) > 0:
		return event["quantity"] * flt(rule.get("hours_per_day")), unit
	frappe.throw("Tidak ada sumber durasi jam untuk kategori ini. Periksa aturan presensi.")


def snapshot_rows(doc):
	value = doc.get("custom_hr_attendance_snapshot")
	if not value:
		return []
	try:
		rows = json.loads(value)
	except (TypeError, ValueError):
		frappe.throw("Snapshot presensi JSON tidak valid. Refresh snapshot pada slip Draft.")
	if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
		frappe.throw("Snapshot presensi harus berupa daftar rincian.")
	return rows


def classify_day(day, attendance, logs, shift, *, leave_quantity=0, has_leave=False, tolerance=0):
	"""One category per day: leave/absence > missing punch > lateness."""
	if has_leave:
		return ({"category": "Izin", "quantity": leave_quantity} if leave_quantity else None), []
	if not attendance:
		return None, ["Attendance Submitted belum tersedia."]
	if attendance.status == "Absent":
		return {"category": "Alpha", "quantity": 1.0}, []
	if attendance.status == "Half Day" and attendance.get("half_day_status") == "Absent":
		return {"category": "Alpha", "quantity": 0.5}, []
	if attendance.status == "On Leave" or (
		attendance.status == "Half Day" and attendance.get("half_day_status") == "On Leave"
	):
		return None, ["Status cuti tidak memiliki Leave Application Approved yang sesuai."]
	if attendance.status == "Work From Home":
		return None, []  # Do not apply outlet punch rules to WFH without an explicit policy.
	if not shift:
		return None, ["Shift belum tersedia; terlambat dan log IN/OUT tidak disimpulkan."]
	start = get_datetime(str(day)) + get_timedelta(shift.start_time)
	end = get_datetime(str(day)) + get_timedelta(shift.end_time)
	if end <= start:
		end += timedelta(days=1)
	window_start = start - timedelta(minutes=flt(shift.get("begin_check_in_before_shift_start_time")))
	window_end = end + timedelta(minutes=flt(shift.get("allow_check_out_after_shift_end_time")))
	relevant = [log for log in logs if log.get("attendance") == attendance.name or (
		not log.get("attendance") and (not log.get("shift") or log.shift == attendance.shift)
		and window_start <= get_datetime(log.time) <= window_end)]
	ins = [get_datetime(log.time) for log in relevant if log.log_type == "IN"]
	outs = [get_datetime(log.time) for log in relevant if log.log_type == "OUT"]
	in_time = get_datetime(attendance.in_time) if attendance.get("in_time") else min(ins, default=None)
	out_time = get_datetime(attendance.out_time) if attendance.get("out_time") else max(outs, default=None)
	if not in_time and not out_time:
		return None, ["Attendance hadir tanpa IN dan OUT: perlu verifikasi, bukan alpha otomatis."]
	if in_time and out_time and out_time < in_time:
		return None, ["Urutan IN/OUT tidak valid: perlu koreksi."]
	if not in_time:
		return {"category": "Tidak Absen IN", "quantity": 1.0}, []
	if not out_time:
		return {"category": "Tidak Absen OUT", "quantity": 1.0}, []
	minutes = max((in_time - start).total_seconds() / 60, 0)
	if minutes > flt(tolerance):
		return {"category": "Terlambat", "quantity": 1.0, "minutes": flt(minutes, 2)}, []
	return None, []


def collect_summary(employee_name, start_date, end_date, today=None):
	if not start_date or not end_date:
		frappe.throw("Tanggal mulai dan akhir wajib diisi.")
	start, end, today = getdate(start_date), getdate(end_date), getdate(today)
	if start > end or date_diff(end, start) > 365:
		frappe.throw("Periode tidak valid atau melebihi 366 hari.")
	employee = frappe.get_doc("Employee", employee_name)
	employee.check_permission("read")
	policies = []
	rules = []
	for name in frappe.get_all(SETTINGS, filters={"company": employee.company, "disabled": 0,
		"from_date": ["<=", end]}, pluck="name", order_by="from_date asc, name asc"):
		settings = frappe.get_doc(SETTINGS, name)
		if settings.to_date and getdate(settings.to_date) < start:
			continue
		policies.append({"name": name, "from_date": settings.from_date, "to_date": settings.to_date,
			"late_tolerance_minutes": settings.late_tolerance_minutes})
		for row in settings.rules:
			rule = {field: row.get(field) for field in RULE_FIELDS}
			rule["company"] = settings.company
			rule["from_date"] = max(getdate(row.from_date or settings.from_date), getdate(settings.from_date))
			ends = [getdate(value) for value in (row.to_date, settings.to_date) if value]
			rule["to_date"] = min(ends) if ends else None
			rule["policy"] = name
			rules.append(rule)
	payroll_based_on = frappe.db.get_single_value("Payroll Settings", "payroll_based_on")
	closed_end = min(end, today - timedelta(days=1))
	if employee.get("relieving_date"):
		closed_end = min(closed_end, getdate(employee.relieving_date))
	active_start = max(start, getdate(employee.date_of_joining)) if employee.date_of_joining else start
	warnings, blockers = [], []
	if end >= today:
		blockers.append("Periode belum selesai; rekap hanya sampai hari kemarin.")
	attendances, leaves, logs, holidays, shifts, assignments = [], [], [], [], [], []
	if active_start <= closed_end:
		attendances = frappe.get_all("Attendance", filters={"employee": employee_name, "docstatus": 1,
			"attendance_date": ["between", [active_start, closed_end]]},
			fields=["name", "attendance_date", "status", "half_day_status", "shift", "in_time", "out_time", "modified"])
		leaves = frappe.get_all("Leave Application", filters={"employee": employee_name, "docstatus": 1,
			"status": "Approved", "from_date": ["<=", closed_end], "to_date": [">=", active_start]},
			fields=["name", "leave_type", "from_date", "to_date", "half_day", "half_day_date", "modified"])
		logs = frappe.get_all("Employee Checkin", filters={"employee": employee_name,
			"time": ["between", [get_datetime(str(active_start)) - timedelta(days=1),
				get_datetime(str(closed_end)) + timedelta(days=2)]]},
			fields=["name", "time", "log_type", "attendance", "shift", "modified"])
		from hrms.hr.utils import get_holidays_for_employee
		holiday_records = get_holidays_for_employee(employee_name, active_start, closed_end, raise_exception=False)
		if holiday_records:
			holiday_info = {row.name: row for row in frappe.get_all("Holiday",
				filters={"name": ["in", [row.name for row in holiday_records]]},
				fields=["name", "holiday_date", "is_half_day", "modified"])}
			holidays = [holiday_info[row.name] for row in holiday_records]
		shift_names = sorted({row.shift for row in attendances if row.shift})
		if shift_names:
			shifts = frappe.get_all("Shift Type", filters={"name": ["in", shift_names]},
				fields=["name", "start_time", "end_time", "begin_check_in_before_shift_start_time",
					"allow_check_out_after_shift_end_time", "modified"])
		assignments = frappe.get_all("Salary Structure Assignment", filters={"employee": employee_name,
			"company": employee.company,
			"docstatus": 1, "from_date": ["<=", closed_end]},
			fields=["name", "from_date", "base", "modified"], order_by="from_date desc")
	leave_types = {row.name: {"is_lwp": row.is_lwp, "include_holiday": row.include_holiday}
		for row in frappe.get_all("Leave Type", filters={"name": ["in", sorted({row.leave_type for row in leaves})]},
			fields=["name", "is_lwp", "include_holiday"])} if leaves else {}
	attendance_by_day = defaultdict(list)
	for row in attendances:
		attendance_by_day[getdate(row.attendance_date)].append(row)
	holiday_by_day = {getdate(row.holiday_date): row for row in holidays}
	shift_map = {row.name: row for row in shifts}
	rows = {}
	day = active_start
	while day <= closed_end:
		day_policies = [policy for policy in policies if getdate(policy["from_date"]) <= day
			and (not policy["to_date"] or day <= getdate(policy["to_date"]))]
		if len(day_policies) > 1:
			frappe.throw("Lebih dari satu aturan presensi aktif untuk perusahaan pada {0}.".format(day))
		tolerance = day_policies[0]["late_tolerance_minutes"] if day_policies else 0
		if day in holiday_by_day:
			if any(getdate(leave.from_date) <= day <= getdate(leave.to_date)
				and cint(leave_types.get(leave.leave_type, {}).get("is_lwp"))
				and cint(leave_types.get(leave.leave_type, {}).get("include_holiday")) for leave in leaves):
				blockers.append(f"{day}: LWP mencakup hari libur; perlu verifikasi manual pada tahap ini.")
			if cint(holiday_by_day[day].is_half_day):
				blockers.append(f"{day}: libur setengah hari perlu verifikasi; belum dihitung otomatis.")
			day += timedelta(days=1)
			continue
		day_attendance = attendance_by_day.get(day, [])
		if len(day_attendance) > 1:
			blockers.append(f"{day}: lebih dari satu Attendance; perlu verifikasi.")
			day += timedelta(days=1)
			continue
		attendance = day_attendance[0] if day_attendance else None
		day_leaves = [row for row in leaves if getdate(row.from_date) <= day <= getdate(row.to_date)]
		if len(day_leaves) > 1:
			blockers.append(f"{day}: izin/cuti bertumpang tindih; perlu verifikasi.")
			day += timedelta(days=1)
			continue
		leave_quantity = 0.0
		if day_leaves and cint(leave_types.get(day_leaves[0].leave_type, {}).get("is_lwp")):
			leave = day_leaves[0]
			half_date = getdate(leave.half_day_date or leave.from_date)
			leave_quantity = 0.5 if cint(leave.half_day) and day == half_date else 1.0
		event, issues = classify_day(day, attendance, logs, shift_map.get(attendance.shift) if attendance else None,
			leave_quantity=leave_quantity, has_leave=bool(day_leaves), tolerance=tolerance)
		blockers.extend(f"{day}: {issue}" for issue in issues)
		if event:
			category, quantity = event["category"], event["quantity"]
			rule = applicable_rule(rules, category, day, employee.company)
			quantity, unit = event_quantity(event, rule)
			component = rule.get("salary_component") if rule else None
			base = next((row.base for row in assignments if getdate(row.from_date) <= day), None)
			native_handled = category == "Izin" or (category == "Alpha" and payroll_based_on == "Attendance")
			if native_handled:
				warnings.append(f"{category}: estimasi tambahan dinolkan untuk mencegah potongan ganda LWP/payment days.")
			if rule and cint(rule.get("enabled")) and rule.get("method") == "Base / Pembagi" and base is None:
				blockers.append(f"{day}: tidak ada SSA Submitted untuk mengambil Base; nominal belum dapat diterapkan.")
			key = (category, component, unit)
			row = rows.setdefault(key, {"category": category, "salary_component": component,
				"quantity": 0.0, "unit": unit, "estimated_amount": 0.0, "source_details": []})
			amount = estimate_amount(quantity, rule, base, native_handled=native_handled)
			row["quantity"] += quantity
			row["estimated_amount"] += amount
			row["source_details"].append({"date": str(day), "attendance": attendance.name if attendance else None,
				"leave_applications": [leave.name for leave in day_leaves], "quantity": quantity,
				"unit": unit, "source_days": event["quantity"],
				"late_minutes": event.get("minutes"), "rule": rule, "base": base,
				"native_handled": native_handled, "estimated_amount": amount})
		day += timedelta(days=1)
	for category in CATEGORIES:
		if not any(key[0] == category for key in rows):
			rule = applicable_rule(rules, category, min(end, today), employee.company)
			component = rule.get("salary_component") if rule else None
			unit = (rule or {}).get("unit") or "Hari"
			rows[(category, component, unit)] = {"category": category, "salary_component": component,
				"quantity": 0.0, "unit": unit, "estimated_amount": 0.0, "source_details": []}
	result_rows = sorted(rows.values(), key=lambda row: (CATEGORIES.index(row["category"]), row["salary_component"] or "", row["unit"]))
	managed_components = sorted({rule["salary_component"] for rule in rules
		if cint(rule.get("enabled")) and rule.get("salary_component")
		and getdate(rule["from_date"]) <= end
		and (not rule["to_date"] or getdate(rule["to_date"]) >= start)})
	for row in result_rows:
		row["managed_by_attendance"] = row["salary_component"] in managed_components
		row["estimated_amount"] = flt(row["estimated_amount"], 2)
		row["source_details"] = json.dumps(row["source_details"], sort_keys=True, default=str)
	payload = {"version": 1, "employee": employee_name, "start_date": start, "end_date": end,
		"as_of": min(end, today - timedelta(days=1)), "policies": policies,
		"rules": rules, "payroll_based_on": payroll_based_on, "attendance": attendances, "leaves": leaves,
		"leave_types": leave_types, "logs": logs, "holidays": holidays, "shifts": shifts,
		"assignments": assignments, "rows": result_rows, "blockers": blockers}
	return {"employee": employee_name, "start_date": str(start), "end_date": str(end),
		"rows": result_rows, "warnings": sorted(set(warnings)), "blockers": blockers,
		"managed_components": managed_components,
		"estimated_total": flt(sum(row["estimated_amount"] for row in result_rows), 2),
		"source_hash": fingerprint(payload), "deductions_changed": False}


@frappe.whitelist()
def preview_attendance(employee, start_date, end_date):
	frappe.only_for(["HR Manager", "System Manager"])
	return collect_summary(employee, start_date, end_date)


@frappe.whitelist(methods=["POST"])
def save_attendance_snapshot(salary_slip):
	frappe.only_for(["HR Manager", "System Manager"])
	doc = frappe.get_doc("Salary Slip", salary_slip)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw("Snapshot hanya dapat diperbarui pada Salary Slip Draft.")
	summary = collect_summary(doc.employee, doc.start_date, doc.end_date)
	doc.custom_hr_attendance_snapshot = json.dumps(summary["rows"], ensure_ascii=False)
	doc.custom_hr_attendance_hash = summary["source_hash"]
	doc.custom_hr_attendance_calculated_on = now_datetime()
	doc.custom_hr_attendance_warnings = "\n".join(summary["warnings"] + summary["blockers"])
	frappe.db.savepoint("attendance_snapshot")
	try:
		doc.save()
	except Exception:
		frappe.db.rollback(save_point="attendance_snapshot")
		raise
	return summary


def validate_snapshot(doc, method=None):
	if not doc.get("custom_hr_attendance_hash") and not doc.get("custom_hr_attendance_snapshot"):
		return  # Existing/native slips without this optional feature are unaffected.
	summary = collect_summary(doc.employee, doc.start_date, doc.end_date)
	if summary["blockers"]:
		frappe.throw("Snapshot presensi belum lengkap. Selesaikan verifikasi sebelum Submit.")
	actual = snapshot_rows(doc)
	if doc.custom_hr_attendance_hash != summary["source_hash"] or actual != summary["rows"]:
		frappe.throw("Sumber/aturan atau rincian presensi berubah. Hitung/simpan ulang Salary Slip sebelum Submit.")
	if summary.get("managed_components"):
		from custom_hr.overrides.salary_slip import validate_deduction_amounts

		validate_deduction_amounts(doc, summary)
