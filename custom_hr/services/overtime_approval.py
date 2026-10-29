"""Employee-scoped overtime decisions, evaluated using the existing workflow."""

from copy import deepcopy

import frappe
from frappe import _
from frappe.model.workflow import get_transitions, has_approval_access
from frappe.utils import now_datetime

DECISION_TOKEN = object()  # Identity cannot be supplied through a JSON document/flags.
TIME_EDIT_TOKEN = object()  # set only by the Working Calendar hour correction of the current approver
SELF_REQUEST_TOKEN = object()  # set only by custom_hr.api.my_overtime, for an employee requesting for themselves
FINAL_STATES = {"Disetujui", "Ditolak"}
PENDING_STATES = ("Menunggu Leader", "Menunggu SPV", "Menunggu HRD")
AUDIT_FIELDS = ("approval_state", "decision_by", "decision_on")
WAITING_FIELDS = {"Menunggu Leader": "approver_1", "Menunggu SPV": "approver_2"}


def employee_state(doc, row):
	return row.get("approval_state") or doc.status


def waiting_for(doc, status):
	"""Who a pending stage waits for, by name; the HRD stage is a role, not one person."""
	user = doc.get(WAITING_FIELDS[status]) if status in WAITING_FIELDS else None
	if user:
		return frappe.db.get_value("User", user, "full_name") or user
	return "HRD" if status == "Menunggu HRD" else None


def stage_label(doc, status):
	"""Working Calendar label: the approver by name, like the leave PL stage."""
	name = waiting_for(doc, status) if status in WAITING_FIELDS else None
	return f"Waiting for {name}" if name else status


def employee_view(doc, row):
	view = deepcopy(doc)
	view.status = employee_state(doc, row)
	return view


def aggregate_state(doc):
	states = [employee_state(doc, row) for row in doc.employees]
	for state in PENDING_STATES:
		if state in states:
			return state
	return "Disetujui" if "Disetujui" in states else "Ditolak"


def protect_employee_decisions(doc):
	if doc.flags.get("employee_decision_token") is DECISION_TOKEN:
		return
	if doc.is_new() or not doc.get("name"):
		if any(row.get(field) for row in doc.employees for field in AUDIT_FIELDS):
			frappe.throw(_("Tahap approval hanya boleh diubah melalui Working Calendar."), frappe.PermissionError)
		return
	old = doc.get_doc_before_save()
	if not old:
		return
	old_rows = {row.name: row for row in old.employees}
	started = any(row.get("approval_state") for row in old.employees)
	for row in doc.employees:
		previous = old_rows.get(row.name)
		if any(str(row.get(field) or "") != str((previous.get(field) if previous else None) or "") for field in AUDIT_FIELDS):
			frappe.throw(_("Tahap approval hanya boleh diubah melalui Working Calendar."), frappe.PermissionError)
	if started:
		fixed = ("date", "start_time", "end_time", "overtime_type", "company", "outlet", "approver_1", "approver_2", "status")
		if doc.flags.get("overtime_time_token") is TIME_EDIT_TOKEN:
			fixed = tuple(field for field in fixed if field not in ("start_time", "end_time"))
		if any(str(doc.get(field) or "") != str(old.get(field) or "") for field in fixed) or [(r.name, r.employee) for r in doc.employees] != [(r.name, r.employee) for r in old.employees]:
			frappe.throw(_("Pengajuan yang sudah diproses per karyawan tidak boleh diubah atau diputuskan sekaligus."))
	elif len(doc.employees) > 1 and doc.status != old.status and doc.flags.get("employee_initialization_token") is not DECISION_TOKEN:
		frappe.throw(_("Gunakan Working Calendar untuk approve/reject setiap karyawan secara terpisah."))


def decide_employee(doc, employee, action, workflow):
	if not workflow or workflow.workflow_state_field != "status":
		frappe.throw(_("Workflow lembur per karyawan belum dikonfigurasi."))
	rows = [row for row in doc.employees if row.employee == employee]
	if len(rows) != 1:
		frappe.throw(_("Karyawan tidak ditemukan pada pengajuan ini."), frappe.PermissionError)
	row = rows[0]
	view = employee_view(doc, row)
	if view.status in FINAL_STATES:
		frappe.throw(_("Pengajuan karyawan ini sudah selesai diproses."))
	transition = next((t for t in get_transitions(view, workflow) if t.action == action and has_approval_access(frappe.session.user, view, t)), None)
	if not transition:
		frappe.throw(_("Anda tidak berhak memproses karyawan ini pada tahap saat ini."), frappe.PermissionError)
	next_state = next(s for s in workflow.states if s.state == transition.next_state)
	if str(next_state.doc_status or "0") != "0" or next_state.update_field or transition.transition_tasks:
		frappe.throw(_("Workflow ini memerlukan penyesuaian sebelum dipakai untuk approval per karyawan."))
	if transition.next_state not in (*PENDING_STATES, *FINAL_STATES):
		frappe.throw(_("Tahap approval lembur tidak didukung."))
	# Freeze legacy rows at the existing request stage before the first decision.
	for member in doc.employees:
		if not member.get("approval_state"):
			member.approval_state = doc.status
	previous = row.approval_state
	row.approval_state = transition.next_state
	row.decision_by = frappe.session.user
	row.decision_on = now_datetime()
	doc.status = aggregate_state(doc)
	doc.flags.employee_decision_token = DECISION_TOKEN
	try:
		doc.save()  # Normal write permission, validation, versioning and side effects.
	finally:
		doc.flags.pop("employee_decision_token", None)
	doc.add_comment("Workflow", _("{0}: {1} → {2}").format(frappe.utils.escape_html(employee), previous, row.approval_state))
	return {"name": doc.name, "employee": employee, "status": row.approval_state, "request_status": doc.status}
