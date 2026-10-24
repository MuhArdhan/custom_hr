"""Date-based approval inbox. Native permissions and workflows remain authoritative."""

from datetime import timedelta

import frappe
from frappe import _
from frappe.model.workflow import (
	apply_workflow,
	get_transitions,
	get_workflow,
	get_workflow_name,
	has_approval_access,
)
from frappe.utils import cint, flt, getdate
from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

from custom_hr.services.overtime_approval import decide_employee, employee_state, employee_view

TYPES = {"leave": "Leave Application", "overtime": "Overtime Request"}
# Overtime implementation is retained, but not enabled in the approval inbox.
ENABLED_KINDS = frozenset({"leave"})
HR_ROLES = {"HR Manager", "System Manager"}
MAX_REQUESTS = 500
LEAVE_CALENDAR_STATUSES = ("leave_request", "approved_leave", "rejected", "cancelled")


def _range(start_date, end_date):
	try:
		if not start_date or not end_date:
			raise ValueError
		start, end = getdate(start_date), getdate(end_date)
		if not 0 <= (end - start).days < 62:
			raise ValueError
	except (ValueError, TypeError, OverflowError):
		frappe.throw(_("Pilih rentang tanggal yang valid, maksimal 62 hari."))
	return start, end


def _workflow(doctype):
	return get_workflow(doctype) if get_workflow_name(doctype) else None


def _actions(doc, workflow=None):
	if doc.doctype == "Overtime Request" and "overtime" not in ENABLED_KINDS:
		return []
	if cint(doc.docstatus) != 0 or not doc.has_permission("read") or not doc.has_permission("write"):
		return []
	if workflow:
		result = []
		for transition in get_transitions(doc, workflow):
			if not has_approval_access(frappe.session.user, doc, transition):
				continue
			label = transition.action.casefold().strip()
			if label.startswith(("setujui", "approve")):
				kind = "approve"
			elif label.startswith(("tolak", "reject")):
				kind = "reject"
			else:
				continue
			result.append({"action": transition.action, "kind": kind, "next_state": transition.next_state})
		return result
	if doc.doctype != "Leave Application" or doc.status != "Open" or not doc.has_permission("submit"):
		return []
	user = frappe.session.user
	is_hr = user == "Administrator" or bool(HR_ROLES & set(frappe.get_roles()))
	if doc.leave_approver != user and not is_hr:
		return []
	prevent_self = cint(frappe.db.get_single_value("HR Settings", "prevent_self_leave_approval"))
	employee_user = frappe.db.get_value("Employee", doc.employee, "user_id")
	result = [{"action": "Reject", "kind": "reject", "next_state": "Rejected"}]
	if not (prevent_self and employee_user == user):
		result.insert(0, {"action": "Approve", "kind": "approve", "next_state": "Approved"})
	return result


def _leave_calendar_status(doc):
	# Native leave status/docstatus, not a PL/intermediate Workflow approval,
	# determines whether this is actual approved leave.
	if cint(doc.docstatus) == 2 or doc.status == "Cancelled":
		return "cancelled"
	if doc.status == "Rejected":
		return "rejected"
	if doc.status == "Approved" and cint(doc.docstatus) == 1:
		return "approved_leave"
	return "leave_request"


def _leave_balance(doc):
	"""Remaining entitlement of the requested leave type, so the approver can judge the request."""
	rules = frappe.db.get_value("Leave Type", doc.leave_type, ["is_lwp", "allow_negative"], as_dict=True) or {}
	if cint(rules.get("is_lwp")):
		return {"leave_balance": None, "exceeds_balance": False}
	# leave_application lets approvers who can read this request (but not the Employee) see the balance
	balance = flt(get_leave_balance_on(doc.employee, doc.leave_type, getdate(doc.from_date), leave_application=doc.name))
	exceeds = flt(doc.total_leave_days) > balance and not cint(rules.get("allow_negative"))
	return {"leave_balance": balance, "exceeds_balance": bool(exceeds)}


def _request(doc, kind, actions, workflow, overtime_row=None):
	if kind == "leave":
		employees = [{"employee": doc.employee, "employee_name": doc.employee_name or doc.employee}]
		start, end = getdate(doc.from_date), getdate(doc.to_date)
		details = doc.leave_type
		if cint(doc.half_day):
			details += " · " + _("Half Day")
		description = doc.description or ""
	else:
		if overtime_row is None:
			frappe.throw(_("Pilih karyawan yang akan diproses."))
		employees = [{"employee": overtime_row.employee, "employee_name": overtime_row.employee_name or overtime_row.employee}]
		start = end = getdate(doc.date)
		details = f"{doc.start_time} – {doc.end_time} ({doc.planned_hours} " + _("jam") + ")"
		description = doc.get("reason") or ""
	return {
		"doctype": doc.doctype, "name": doc.name, "kind": kind,
		"employee": employees[0]["employee"],
		"calendar_status": _leave_calendar_status(doc) if kind == "leave" else None,
		"from_date": str(start), "to_date": str(end), "employees": employees,
		"status": employee_state(doc, overtime_row) if overtime_row else (doc.get(workflow.workflow_state_field) if workflow else doc.status),
		"details": details, "description": description, "company": doc.company,
		"outlet": frappe.db.get_value("Employee", doc.employee, "outlet") if kind == "leave" else doc.get("outlet"),
		"modified": str(doc.modified), "actions": actions,
		**(_leave_balance(doc) if kind == "leave" else {}),
	}


@frappe.whitelist(methods=["GET"])
def get_leave_calendar(start_date, end_date, employee=None, company=None, kind=None):
	"""Readable requests at every stage; actions remain native permission-gated."""
	start, end = _range(start_date, end_date)
	if kind and kind not in TYPES:
		frappe.throw(_("Jenis pengajuan tidak valid."))
	if kind and kind not in ENABLED_KINDS:
		frappe.throw(_("Approval lembur di Leave Calendar dinonaktifkan sementara. Fokus saat ini cuti/izin."))
	items = []
	for category, doctype in TYPES.items():
		if category not in ENABLED_KINDS:
			continue
		if kind and kind != category:
			continue
		if not frappe.has_permission(doctype, "read"):
			continue
		workflow = _workflow(doctype)
		filters = {}
		if company:
			filters["company"] = company
		if category == "leave":
			filters.update(from_date=["<=", end], to_date=[">=", start])
			if employee:
				filters["employee"] = employee
		else:
			filters["docstatus"] = 0
			filters["date"] = ["between", [start, end]]
			filters["status"] = ["not in", ["Disetujui", "Ditolak"]]
		# Never use get_all/ignore_permissions: list counts must not leak other teams.
		rows = frappe.get_list(doctype, filters=filters, fields=["name"], order_by="creation asc", limit_page_length=MAX_REQUESTS + 1)
		if len(rows) > MAX_REQUESTS:
			frappe.throw(_("Terlalu banyak pengajuan. Persempit rentang tanggal atau filter."))
		for row in rows:
			doc = frappe.get_doc(doctype, row.name)
			if not doc.has_permission("read"):
				continue
			members = doc.employees if category == "overtime" else [None]
			for member in members:
				if member and employee and member.employee != employee:
					continue
				view = employee_view(doc, member) if member else doc
				actions = _actions(view, workflow)
				if category == "leave" or actions:
					item = _request(doc, category, actions, workflow, member)
					if getdate(item["from_date"]) <= end and getdate(item["to_date"]) >= start:
						items.append(item)
	return {"items": items, "counts": _tally(items, start, end), "start_date": str(start), "end_date": str(end)}


def _tally(items, start, end):
	counts = {}
	for item in items:
		day, last = max(start, getdate(item["from_date"])), min(end, getdate(item["to_date"]))
		while day <= last:
			day_counts = counts.setdefault(str(day), {"leave": 0, "overtime": 0, **{s: 0 for s in LEAVE_CALENDAR_STATUSES}})
			day_counts[item["kind"]] += 1
			if item["kind"] == "leave":
				day_counts[item["calendar_status"]] += 1
			day += timedelta(days=1)
	return counts


@frappe.whitelist(methods=["GET"])
def get_leave_counts(start_date, end_date, employee=None, company=None):
	"""Month-grid counts only: one list query, no per-document load or workflow evaluation.

	Rows come from get_list, so permission conditions still scope what each user counts.
	Day details and actions stay in get_leave_calendar.
	"""
	start, end = _range(start_date, end_date)
	if not frappe.has_permission("Leave Application", "read"):
		return {"counts": {}, "total": 0, "start_date": str(start), "end_date": str(end)}
	filters = {"from_date": ["<=", end], "to_date": [">=", start]}
	if company:
		filters["company"] = company
	if employee:
		filters["employee"] = employee
	rows = frappe.get_list(
		"Leave Application", filters=filters, fields=["from_date", "to_date", "status", "docstatus"], limit_page_length=0
	)
	items = [
		{"kind": "leave", "calendar_status": _leave_calendar_status(row), "from_date": row.from_date, "to_date": row.to_date}
		for row in rows
	]
	return {"counts": _tally(items, start, end), "total": len(items), "start_date": str(start), "end_date": str(end)}


@frappe.whitelist(methods=["POST"])
def decide_approval(doctype, name, action, modified, employee=None):
	"""Recheck authority/state under a row lock; run the real document lifecycle."""
	if doctype not in TYPES.values() or not name or not modified:
		frappe.throw(_("Pengajuan tidak valid."))
	if doctype == "Overtime Request" and "overtime" not in ENABLED_KINDS:
		frappe.throw(_("Approval lembur di Leave Calendar dinonaktifkan sementara. Fokus saat ini cuti/izin."))
	# Verify read access before acquiring locks, and never trust a client document.
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	frappe.db.get_value(doctype, name, "name", for_update=True)
	doc.reload()
	if str(doc.modified) != modified:
		frappe.throw(_("Pengajuan sudah berubah. Muat ulang daftar sebelum memproses."))
	workflow = _workflow(doctype)
	if doctype == "Overtime Request":
		if not employee:
			frappe.throw(_("Pilih karyawan yang akan diproses."))
		row = next((r for r in doc.employees if r.employee == employee), None)
		allowed = _actions(employee_view(doc, row), workflow) if row else []
		if action not in {item["action"] for item in allowed}:
			frappe.throw(_("Anda tidak berhak memproses karyawan ini."), frappe.PermissionError)
		return decide_employee(doc, employee, action, workflow)
	if employee and employee != doc.employee:
		frappe.throw(_("Karyawan tidak sesuai dengan pengajuan."), frappe.PermissionError)
	allowed = _actions(doc, workflow)
	if action not in {item["action"] for item in allowed}:
		frappe.throw(_("Anda tidak berhak memproses pengajuan ini pada tahap saat ini."), frappe.PermissionError)
	if workflow:
		result = apply_workflow(doc, action)
	else:
		doc.status = "Approved" if action == "Approve" else "Rejected"
		doc.submit()
		result = doc
	return {"name": result.name, "status": result.get(workflow.workflow_state_field) if workflow else result.status}
