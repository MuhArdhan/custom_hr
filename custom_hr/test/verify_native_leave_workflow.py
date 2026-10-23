"""Explicit rollback-only local verification of native Frappe Workflow documents."""

import frappe
from unittest.mock import patch

from frappe.model.workflow import apply_workflow, get_transitions, get_workflow
from custom_hr.api.leave_calendar import get_leave_calendar, decide_approval
from custom_hr.patches.setup_native_leave_workflow import NAME, STATE_FIELD


def execute():
	previous = frappe.session.user
	frappe.db.savepoint("verify_native_leave")
	try:
		with patch("frappe.sendmail"):
			_verify()
	finally:
		frappe.db.rollback(save_point="verify_native_leave")
		frappe.set_user(previous)
	return "Native PL -> HRD, both rejection paths, native ledger/Attendance and one-level Company verified; all test effects rolled back."


def _new(day, employee="HR-EMP-00008"):
	frappe.set_user("Administrator")
	doc = frappe.get_doc(dict(doctype="Leave Application", employee=employee,
		leave_approver="Administrator", leave_type="Leave Without Pay", from_date=day,
		to_date=day, status="Open", description="[ROLLBACK ONLY] Native Workflow verification")).insert()
	assert type(doc).__name__ == "LeaveApplication", type(doc)
	assert doc.get(STATE_FIELD) == "Open"
	return doc


def _decide(user, doc, action):
	frappe.set_user(user)
	rows = [r for r in get_leave_calendar(str(doc.from_date), str(doc.to_date), kind="leave")["items"] if r["name"] == doc.name]
	assert len(rows) == 1, (user, rows)
	decide_approval(doc.doctype, doc.name, action, rows[0]["modified"], employee=doc.employee)
	doc.reload()


def _verify():
	assert get_workflow("Leave Application").name == NAME
	doc = _new("2026-11-17")
	assert [t.action for t in get_transitions(doc)] == ["Ajukan ke PL"]
	apply_workflow(doc, "Ajukan ke PL")
	doc.reload()
	assert doc.get(STATE_FIELD) == "Menunggu PL"
	assert doc.leave_approver == "workflow.leader@example.com"
	frappe.set_user("workflow.hrd@example.com")
	assert not get_transitions(doc), "HRD shortcut at PL stage"
	rows = [r for r in get_leave_calendar(str(doc.from_date), str(doc.to_date), kind="leave")["items"] if r["name"] == doc.name]
	assert len(rows) == 1 and rows[0]["actions"] == [], "HRD must see the PL-stage request read-only"
	frappe.set_user("workflow.spv@example.com")
	# A SPV need not have read permission. Test transitions only if it does.
	if doc.has_permission("read"):
		assert not get_transitions(doc)
	baseline = {dt: frappe.db.count(dt) for dt in ["Attendance", "Leave Ledger Entry"]}
	_decide("workflow.leader@example.com", doc, "Approve")
	assert doc.get(STATE_FIELD) == "Menunggu HRD" and doc.status == "Open" and doc.docstatus == 0
	assert all(frappe.db.count(dt) == n for dt, n in baseline.items())
	frappe.set_user("workflow.leader@example.com")
	rows = [r for r in get_leave_calendar(str(doc.from_date), str(doc.to_date), kind="leave")["items"] if r["name"] == doc.name]
	assert len(rows) == 1 and rows[0]["actions"] == [], "PL must still see the HRD-stage request read-only"
	assert rows[0]["calendar_status"] == "leave_request", "PL approval must not count as actual leave"
	_decide("workflow.hrd@example.com", doc, "Approve")
	assert doc.docstatus == 1 and doc.status == "Approved" and doc.get(STATE_FIELD) == "Approved"
	rows = [r for r in get_leave_calendar(str(doc.from_date), str(doc.to_date), kind="leave")["items"] if r["name"] == doc.name]
	assert len(rows) == 1 and rows[0]["actions"] == [], "Completed requests remain visible read-only"
	assert rows[0]["calendar_status"] == "approved_leave", "Final approval changes Leave Request to Leave"
	counts = get_leave_calendar(str(doc.from_date), str(doc.to_date), kind="leave")["counts"][str(doc.from_date)]
	assert counts["approved_leave"] >= 1
	assert frappe.db.exists("Leave Ledger Entry", {"transaction_name": doc.name, "docstatus": 1})
	assert frappe.db.exists("Attendance", {"employee": doc.employee, "attendance_date": doc.from_date, "status": "On Leave", "docstatus": 1})
	for day, at_hrd in [("2026-11-18", False), ("2026-11-19", True)]:
		rejected = _new(day)
		apply_workflow(rejected, "Ajukan ke PL")
		rejected.reload()
		if at_hrd:
			_decide("workflow.leader@example.com", rejected, "Approve")
		_decide("workflow.hrd@example.com" if at_hrd else "workflow.leader@example.com", rejected, "Reject")
		assert rejected.docstatus == 1 and rejected.status == "Rejected"
		assert not frappe.db.exists("Leave Ledger Entry", {"transaction_name": rejected.name})
		assert not frappe.db.exists("Attendance", {"employee": rejected.employee, "attendance_date": day, "docstatus": 1})
	company = _new("2026-11-20", "HR-EMP-00001")
	actions = {t.action for t in get_transitions(company)}
	assert actions == {"Approve", "Reject"}, actions
	apply_workflow(company, "Reject")
	company.reload()
	assert company.status == "Rejected" and company.docstatus == 1
