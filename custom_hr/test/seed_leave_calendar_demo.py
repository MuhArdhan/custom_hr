"""Explicit local Leave Calendar demo seeder; no automatic business effects."""

from contextlib import ExitStack
from unittest.mock import patch

import frappe
from frappe.utils import getdate

MARKER = "[DEMO APPROVAL OCT-2026]"


def execute():
	if frappe.session.user != "Administrator":
		frappe.throw("Demo seeder requires Administrator", frappe.PermissionError)
	# Fixed cohort chosen from existing active employees; never change their masters.
	people = [frappe.get_doc("Employee", name) for name in ["HR-EMP-00001", "HR-EMP-00002", "HR-EMP-00003"]]
	if any(p.status != "Active" for p in people):
		frappe.throw("Demo employee is no longer active")
	result = {"marker": MARKER, "leave": [], "overtime": [], "assignments_created": [], "skipped": []}
	with ExitStack() as stack:
		# Demo creation must not send employees/approvers emails or push notices.
		stack.enter_context(patch("frappe.sendmail"))
		for method in ["notify_approver", "notify_leave_approver", "notify_approval_status", "publish_update"]:
			stack.enter_context(patch("hrms.hr.doctype.leave_application.leave_application.LeaveApplication." + method))
		for day in ["2026-10-23", "2026-10-26", "2026-10-28", "2026-10-30"]:
			for person in people:
				label = f"{MARKER} {day} {person.name}"
				existing = frappe.db.get_value("Leave Application", {"description": label}, "name")
				if existing:
					result["leave"].append(existing)
					continue
				if frappe.db.exists("Leave Application", {"employee": person.name, "from_date": ["<=", day], "to_date": [">=", day], "docstatus": ["<", 2], "status": ["in", ["Open", "Approved"]]}):
					result["skipped"].append({"employee": person.name, "date": day, "reason": "existing_leave"})
					continue
				doc = frappe.get_doc({"doctype": "Leave Application", "employee": person.name, "leave_type": "Leave Without Pay", "from_date": day, "to_date": day, "status": "Open", "leave_approver": person.leave_approver or "Administrator", "description": label}).insert()
				result["leave"].append(doc.name)
		for day in ["2026-10-24", "2026-10-27", "2026-10-29", "2026-10-31"]:
			label = f"{MARKER} {day}"
			existing = frappe.db.get_value("Overtime Request", {"reason": label}, "name")
			if existing:
				result["overtime"].append(existing)
				continue
			for person in people:
				assignments = frappe.get_all("Shift Assignment", filters={"employee": person.name, "docstatus": 1, "status": "Active", "start_date": ["<=", day]}, fields=["name", "end_date"])
				if not any(a.end_date and getdate(a.end_date) >= getdate(day) for a in assignments):
					if any(not a.end_date for a in assignments):
						frappe.throw("An open-ended assignment needs manual review before seeding demo overtime")
					assignment = frappe.get_doc({"doctype": "Shift Assignment", "employee": person.name, "company": person.company, "shift_type": "Shift 2 10.00 - 18.00", "start_date": day, "end_date": day, "status": "Active"}).insert()
					assignment.submit()
					assignment.add_comment(text=label + " — prerequisite for demo overtime; not a production roster decision")
					result["assignments_created"].append(assignment.name)
			doc = frappe.get_doc({"doctype": "Overtime Request", "company": people[0].company, "date": day, "start_time": "19:00:00", "end_time": "21:00:00", "overtime_type": "Lembur", "requested_by": "Administrator", "reason": label, "employees": [{"employee": p.name} for p in people]}).insert()
			result["overtime"].append(doc.name)
	return result
