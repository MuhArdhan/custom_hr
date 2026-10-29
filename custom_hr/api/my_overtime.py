# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Overtime the employee requests for themselves from the HRMS app.

Each request is an ordinary Overtime Request holding only that employee, so it goes
through the same Leader -> SPV -> HRD approval and the same payroll chain.
The employee always comes from the session, never from the payload.
"""

import frappe
from frappe import _
from frappe.utils import nowdate
from hrms.api import get_current_employee

from custom_hr.services.overtime_approval import PENDING_STATES, SELF_REQUEST_TOKEN, employee_state, waiting_for

HISTORY_LIMIT = 30
DEFAULT_OVERTIME_TYPE = "Lembur"


def _can_cancel(doc, employee):
	"""Only the employee's own, single-person request, until it is finally approved or rejected."""
	return (
		doc.requested_by == frappe.session.user
		and [row.employee for row in doc.employees] == [employee]
		and employee_state(doc, doc.employees[0]) in PENDING_STATES  # also after a Working Calendar step
	)


@frappe.whitelist(methods=["GET"])
def get_my_overtime() -> dict:
	"""Today's date for the form, and the requests the employee is part of (own or made by a leader)."""
	employee = get_current_employee()
	parents = frappe.get_all(
		"Overtime Request Employee", filters={"employee": employee, "parenttype": "Overtime Request"}, pluck="parent",
	)
	names = frappe.get_all(
		"Overtime Request", filters={"name": ["in", parents]}, order_by="date desc, creation desc", page_length=HISTORY_LIMIT, pluck="name",
	) if parents else []
	history = []
	for name in names:
		doc = frappe.get_doc("Overtime Request", name)
		row = next(row for row in doc.employees if row.employee == employee)
		status = employee_state(doc, row)
		history.append({
			"doctype": "Overtime Request", "name": doc.name, "creation": str(doc.creation), "date": str(doc.date), "overtime_type": doc.overtime_type, "start_time": str(doc.start_time), "end_time": str(doc.end_time),
			"planned_hours": doc.planned_hours, "reason": doc.reason, "status": status, "waiting_for": waiting_for(doc, status), "can_cancel": _can_cancel(doc, employee),
		})
	types = frappe.get_all("Overtime Type", fields=["name", "maximum_overtime_hours_allowed as max_hours"], order_by="name asc")
	names = [row.name for row in types]
	return {
		"date": nowdate(), "history": history,
		"overtime_types": [{"name": row.name, "max_hours": row.max_hours or 0} for row in types],  # 0 = no cap
		"default_overtime_type": DEFAULT_OVERTIME_TYPE if DEFAULT_OVERTIME_TYPE in names else (names[0] if names else None),
	}


@frappe.whitelist(methods=["POST"])
def submit_my_overtime(start_time, end_time, reason, overtime_type=None) -> dict:
	"""Create an Overtime Request for the logged-in employee, always for today (the server's date)."""
	employee = get_current_employee()
	if not (reason or "").strip():
		frappe.throw(_("Alasan lembur wajib diisi."))
	overtime_type = overtime_type or DEFAULT_OVERTIME_TYPE
	if not isinstance(overtime_type, str) or not frappe.db.exists("Overtime Type", overtime_type):
		frappe.throw(_("Jenis lembur tidak ditemukan. Pilih jenis lembur yang tersedia."))

	info = frappe.db.get_value("Employee", employee, ["outlet", "company"], as_dict=True)
	doc = frappe.get_doc({
		"doctype": "Overtime Request", "outlet": info.outlet, "company": info.company, "date": nowdate(),
		"overtime_type": overtime_type, "start_time": start_time, "end_time": end_time, "reason": reason.strip(),
		"requested_by": frappe.session.user, "employees": [{"employee": employee}],
	})
	doc.flags.overtime_self_request = SELF_REQUEST_TOKEN
	doc.insert(ignore_permissions=True)  # the controller still runs every overtime rule; see is_self_request
	return {"name": doc.name, "status": frappe.db.get_value("Overtime Request", doc.name, "status")}


@frappe.whitelist(methods=["POST"])
def cancel_my_overtime(name) -> dict:
	"""Withdraw the employee's own pending request. Nothing reached the shift or payroll yet, so it is deleted."""
	employee = get_current_employee()
	if not frappe.db.exists("Overtime Request", name):
		frappe.throw(_("Pengajuan lembur tidak ditemukan."), frappe.PermissionError)
	doc = frappe.get_doc("Overtime Request", name)
	if employee not in [row.employee for row in doc.employees]:  # a missing and a foreign request look the same
		frappe.throw(_("Pengajuan lembur tidak ditemukan."), frappe.PermissionError)
	if not _can_cancel(doc, employee):
		frappe.throw(_("Pengajuan ini sudah diproses dan tidak dapat dibatalkan."))
	frappe.delete_doc("Overtime Request", name, ignore_permissions=True)
	return {"name": name, "cancelled": True}
