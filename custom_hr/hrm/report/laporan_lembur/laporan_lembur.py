# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Laporan Lembur: jam rencana (pengajuan) vs jam lembur aktual (Attendance)."""

import frappe
from frappe import _

from custom_hr.api.overtime import _sees_all, _their_outlets


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"fieldname": "date", "label": _("Tanggal"), "fieldtype": "Date", "width": 100},
		{
			"fieldname": "outlet",
			"label": _("Outlet"),
			"fieldtype": "Link",
			"options": "Outlet",
			"width": 200,
		},
		{"fieldname": "employee_name", "label": _("Karyawan"), "fieldtype": "Data", "width": 160},
		{
			"fieldname": "shift",
			"label": _("Shift"),
			"fieldtype": "Link",
			"options": "Shift Type",
			"width": 110,
		},
		{"fieldname": "planned_hours", "label": _("Jam Rencana"), "fieldtype": "Float", "width": 100},
		{"fieldname": "actual_hours", "label": _("Jam Aktual"), "fieldtype": "Float", "width": 100},
		{
			"fieldname": "overtime_type",
			"label": _("Jenis Lembur"),
			"fieldtype": "Link",
			"options": "Overtime Type",
			"width": 110,
		},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 140},
	]


def get_data(filters):
	values = frappe._dict()
	conditions = []

	if filters.get("from_date"):
		conditions.append("otr.date >= %(from_date)s")
		values.from_date = filters.from_date
	if filters.get("to_date"):
		conditions.append("otr.date <= %(to_date)s")
		values.to_date = filters.to_date
	if filters.get("outlet"):
		conditions.append("otr.outlet = %(outlet)s")
		values.outlet = filters.outlet
	if filters.get("status"):
		conditions.append("COALESCE(NULLIF(otre.approval_state, ''), otr.status) = %(status)s")
		values.status = filters.status

	if not _sees_all(frappe.session.user):
		outlets = _their_outlets(frappe.session.user)
		if not outlets:
			return []
		conditions.append("otr.outlet in %(outlets)s")
		values.outlets = outlets

	where = " and ".join(conditions) or "1=1"
	rows = frappe.db.sql(
		"""
		select
			otr.date, otr.outlet, otre.employee_name, otre.shift,
			otr.planned_hours, otr.overtime_type,
			COALESCE(NULLIF(otre.approval_state, ''), otr.status) AS status,
			att.actual_overtime_duration as actual_hours
		from `tabOvertime Request` otr
		join `tabOvertime Request Employee` otre on otre.parent = otr.name
		left join `tabAttendance` att
			on att.employee = otre.employee
			and att.attendance_date = otr.date
			and att.docstatus = 1
			and ifnull(att.overtime_type, '') != ''
		where {0}
		order by otr.date desc, otre.employee_name
		""".format(where),
		values,
		as_dict=True,
	)
	for row in rows:
		row.actual_hours = round(row.actual_hours, 2) if row.actual_hours else None
	return rows
