# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Roster APIs: month grid of shift assignments for one outlet."""

import frappe
from frappe import _
from frappe.utils import add_days, getdate

HR_ROLES = ("HR Manager", "HR User", "System Manager")
WEEKDAY_ID = {
	"Monday": "Senin",
	"Tuesday": "Selasa",
	"Wednesday": "Rabu",
	"Thursday": "Kamis",
	"Friday": "Jumat",
	"Saturday": "Sabtu",
	"Sunday": "Minggu",
}


@frappe.whitelist()
def list_outlets():
	"""Outlets the current user may plan for."""
	allowed = _allowed_outlets()
	if allowed is None:
		allowed = frappe.get_all(
			"Outlet",
			filters={"is_active": 1},
			pluck="name",
			order_by="name",
			ignore_permissions=True,
		)
	return allowed


@frappe.whitelist()
def get_roster(outlet: str, start_date: str, end_date: str):
	_check_outlet_access(outlet)

	employees = frappe.get_all(
		"Employee",
		filters={"outlet": outlet, "status": "Active"},
		fields=["name", "employee_name"],
		order_by="employee_name",
		ignore_permissions=True,
	)
	names = [employee.name for employee in employees]
	return {
		"employees": [{"value": e.name, "label": e.employee_name} for e in employees],
		"shifts": _shift_map(names, start_date, end_date),
		"holidays": {name: _holiday_map(name, start_date, end_date) for name in names},
		"shift_options": _shift_options(outlet),
	}


@frappe.whitelist()
def set_shift(outlet: str, employee: str, date: str, shift_type: str | None = None):
	_check_outlet_access(outlet)
	if frappe.db.get_value("Employee", employee, "outlet") != outlet:
		frappe.throw(_("Karyawan tidak berada di outlet ini"), frappe.PermissionError)

	_remove_assignments(employee, date)
	if shift_type:
		_set_assignment(employee, date, shift_type)

	frappe.db.commit()
	return {"employee": employee, "date": date, "shift_type": shift_type}


@frappe.whitelist()
def swap_off_days(
	outlet: str,
	work_date: str,
	off_date: str,
	shift_type: str | None = None,
	employees: str | None = None,
):
	"""Move selected employees' work from off_date to work_date (libur ditukar)."""
	_check_outlet_access(outlet)
	if not work_date or not off_date or work_date == off_date:
		frappe.throw(_("Tanggal kerja dan tanggal libur harus berbeda"))

	outlet_employees = frappe.get_all(
		"Employee", filters={"outlet": outlet, "status": "Active"}, pluck="name", ignore_permissions=True
	)
	selected = frappe.parse_json(employees) if employees else outlet_employees
	selected = [employee for employee in selected if employee in outlet_employees]
	if not selected:
		frappe.throw(_("Tidak ada karyawan yang dipilih"))

	blocked = [employee for employee in selected if _holiday_map(employee, work_date, work_date)]
	if blocked:
		names = ", ".join(
			frappe.db.get_value("Employee", employee, "employee_name") or employee for employee in blocked
		)
		frappe.throw(
			_("Tanggal kerja {0} adalah hari libur untuk: {1}").format(frappe.bold(work_date), names)
		)

	moved = skipped = 0
	for employee in selected:
		target_shift = shift_type or _assignment_on(employee, off_date)
		_remove_assignments(employee, off_date)
		if target_shift:
			_remove_assignments(employee, work_date)
			_set_assignment(employee, work_date, target_shift)
			moved += 1
		elif _assignment_on(employee, work_date):
			moved += 1
		else:
			skipped += 1

	frappe.db.commit()
	return {"moved": moved, "skipped": skipped}


def _check_outlet_access(outlet):
	allowed = _allowed_outlets()
	if allowed is not None and outlet not in allowed:
		frappe.throw(_("Anda tidak punya akses ke outlet ini"), frappe.PermissionError)


def _allowed_outlets():
	user = frappe.session.user
	if set(HR_ROLES) & set(frappe.get_roles(user)):
		return None

	outlets = frappe.get_all(
		"Outlet",
		filters={"is_active": 1},
		or_filters=[["approver_1", "=", user], ["approver_2", "=", user]],
		pluck="name",
		ignore_permissions=True,
	)
	if not outlets:
		frappe.throw(
			_("Anda tidak terdaftar sebagai approver outlet mana pun"), frappe.PermissionError
		)
	return outlets


def _shift_map(employees, start_date, end_date):
	if not employees:
		return {}

	rows = frappe.get_all(
		"Shift Assignment",
		filters={
			"employee": ["in", employees],
			"docstatus": ["!=", 2],
			"status": "Active",
			"start_date": ["<=", end_date],
			"end_date": [">=", start_date],
		},
		fields=["employee", "shift_type", "start_date", "end_date"],
		ignore_permissions=True,
	)
	result = {}
	for row in rows:
		day = max(getdate(row.start_date), getdate(start_date))
		last = min(getdate(row.end_date or row.start_date), getdate(end_date))
		while day <= last:
			result.setdefault(row.employee, {})[str(day)] = row.shift_type
			day = add_days(day, 1)
	return result


def _holiday_map(employee, start_date, end_date):
	from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee

	holiday_list = get_holiday_list_for_employee(employee, raise_exception=False)
	if not holiday_list:
		return {}

	holidays = {}
	weekly_off = frappe.db.get_value("Holiday List", holiday_list, "weekly_off")
	if weekly_off:
		day = getdate(start_date)
		while day <= getdate(end_date):
			if day.strftime("%A") == weekly_off:
				holidays[str(day)] = WEEKDAY_ID.get(weekly_off, weekly_off)
			day = add_days(day, 1)

	rows = frappe.get_all(
		"Holiday",
		filters={"parent": holiday_list, "holiday_date": ["between", [start_date, end_date]]},
		fields=["holiday_date", "description"],
		ignore_permissions=True,
	)
	for row in rows:
		holidays[str(row.holiday_date)] = row.description or _("Libur")
	return holidays


def _shift_options(outlet):
	rows = frappe.get_all(
		"Outlet Shift",
		filters={"parent": outlet, "enabled": 1},
		fields=["shift_type", "valid_to"],
		ignore_permissions=True,
	)
	options = []
	for row in rows:
		if row.valid_to and getdate(row.valid_to) < getdate():
			continue  # temporary shift that has already ended
		color = frappe.db.get_value("Shift Type", row.shift_type, "color") or "Blue"
		options.append({"value": row.shift_type, "label": row.shift_type, "color": color})
	return options


def _remove_assignments(employee, date):
	rows = frappe.get_all(
		"Shift Assignment",
		filters={
			"employee": employee,
			"docstatus": ["!=", 2],
			"start_date": ["<=", date],
			"end_date": [">=", date],
		},
		fields=["name", "start_date", "end_date"],
		ignore_permissions=True,
	)
	for row in rows:
		doc = frappe.get_doc("Shift Assignment", row.name)
		start, end = getdate(row.start_date), getdate(row.end_date or row.start_date)
		splits = []
		if start < getdate(date):
			splits.append((row.start_date, add_days(date, -1)))
		if end > getdate(date):
			splits.append((add_days(date, 1), row.end_date))
		# cancel first so the recreated splits don't trip the overlap validation
		if doc.docstatus == 1:
			doc.flags.ignore_permissions = True
			doc.cancel()
		for split_start, split_end in splits:
			_duplicate_assignment(doc, split_start, split_end)
		frappe.delete_doc("Shift Assignment", row.name, ignore_permissions=True, force=True)


def _set_assignment(employee, date, shift_type):
	assignment = frappe.get_doc(
		{
			"doctype": "Shift Assignment",
			"employee": employee,
			"employee_name": frappe.db.get_value("Employee", employee, "employee_name"),
			"company": frappe.db.get_value("Employee", employee, "company"),
			"shift_type": shift_type,
			"start_date": date,
			"end_date": date,
			"status": "Active",
		}
	)
	assignment.insert(ignore_permissions=True)
	# HRMS only reads submitted assignments for check-in/attendance
	assignment.flags.ignore_permissions = True
	assignment.submit()


def _assignment_on(employee, date):
	rows = frappe.get_all(
		"Shift Assignment",
		filters={
			"employee": employee,
			"docstatus": ["!=", 2],
			"status": "Active",
			"start_date": ["<=", date],
			"end_date": [">=", date],
		},
		fields=["shift_type"],
		ignore_permissions=True,
	)
	return rows[0].shift_type if rows else None


def _duplicate_assignment(source, start_date, end_date):
	copy = frappe.copy_doc(source)
	copy.start_date = start_date
	copy.end_date = end_date
	copy.insert(ignore_permissions=True)
	copy.flags.ignore_permissions = True
	copy.submit()
