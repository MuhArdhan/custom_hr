# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Self-service context is advisory; the shared lifecycle rechecks on insert."""

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate, now_datetime

from hrms.api import get_current_employee

from custom_hr.hrm.doctype.outlet import outlet as outlet_configuration
from custom_hr.services.checkin_submission import (
	RESPONSE_FIELDS, checkin_response, request_log_name, submit_self_checkin,
)
from custom_hr.services.outlet_checkin import (
	_checkout_snapshot,
	_cutoff,
	_employee_record,
	_has_out,
	_latest_in_for_checkout,
	validate_new_in_session,
)
from custom_hr.services.outlet_shift import normalize_checkin_datetime, resolve_outlet_shift


@frappe.whitelist(methods=["POST"])
def validate_checkin_location(latitude=None, longitude=None, log_type=None, expected_checkin=None):
	"""Advisory preflight only: no punch, face verification or attendance writes."""
	from hrms.hr.doctype.employee_checkin.employee_checkin import EmployeeCheckin
	from custom_hr.services.outlet_geofence import validate_outlet_geofence

	context = get_checkin_context()
	if not context["allowed"]:
		frappe.throw(context["message"] or _("Attendance is not available."))
	if log_type != context["next_action"] or (expected_checkin or None) != context["paired_checkin"]:
		frappe.throw(_("Attendance status changed. Close this dialog and try again."))
	if not cint(frappe.db.get_single_value("HR Settings", "allow_geolocation_tracking")):
		return {"valid": True}
	probe = frappe.get_doc({
		"doctype": "Employee Checkin", "employee": context["employee"],
		"time": context["server_time"], "log_type": log_type,
		"latitude": latitude, "longitude": longitude,
		"attendance_source": context["mode"], "outlet_at_checkin": context["outlet"],
	})
	if not validate_outlet_geofence(probe):
		# Call native methods directly; the override prepares a real session and
		# requires face verification, neither of which belongs in a location probe.
		EmployeeCheckin.fetch_shift(probe)
		EmployeeCheckin.validate_distance_from_shift_location(probe)
	return {"valid": True}


@frappe.whitelist(methods=["POST"])
def submit_checkin(log_type: str, latitude=None, longitude=None, request_id: str | None = None, expected_checkin: str | None = None):
	doc, replayed = submit_self_checkin(
		get_current_employee(), log_type,
		latitude=latitude, longitude=longitude, request_id=request_id, expected_checkin=expected_checkin,
	)
	return checkin_response(doc, replayed=replayed)


@frappe.whitelist(methods=["GET"])
def get_checkin_request_result(request_id: str):
	"""Read only one's committed result after an uncertain network response.

	Not found is NOT permission to create a new action: the original request
	may still be running. Clients must retain the UUID until resolved/retried.
	"""
	employee = get_current_employee()
	record = _employee_record(employee, for_update=False)
	if record.user_id != frappe.session.user or record.status != "Active":
		frappe.throw(_("Akun harus terhubung ke karyawan aktif yang sedang login."), frappe.PermissionError)
	name = request_log_name(employee, request_id)
	if not name:
		frappe.throw(_("request_id wajib diisi untuk memeriksa hasil permintaan."))
	row = frappe.db.get_value(
		"Employee Checkin", name, list(RESPONSE_FIELDS), as_dict=True,
	)
	if row and row.employee != employee:
		frappe.throw(_("Hasil permintaan bukan milik karyawan ini."), frappe.PermissionError)
	return checkin_response(row, replayed=True) if row else None


@frappe.whitelist()
def get_checkin_context():
	employee = get_current_employee()
	record = _employee_record(employee, for_update=False)
	if record.user_id != frappe.session.user or record.status != "Active":
		frappe.throw(_("Akun harus terhubung ke karyawan aktif yang sedang login."), frappe.PermissionError)
	now = normalize_checkin_datetime(now_datetime())
	context = {
		"employee": employee, "server_time": str(now), "outlet": record.outlet,
		"mode": "Native", "next_action": "IN", "allowed": True, "reason": None,
		"message": "", "candidate_shift": None, "shift_work_date": str(now.date()),
		"checkout_deadline": None, "paired_checkin": None,
		"incomplete_session": None,
	}

	def block(reason, message, action=None):
		context.update(allowed=False, reason=reason, message=message)
		if action:
			context["next_action"] = action
		return context

	def use_session(row):
		context.update(
			mode="Outlet" if row.attendance_source == "Outlet" else "Native",
			outlet=row.outlet_at_checkin or record.outlet, candidate_shift=row.shift,
			paired_checkin=row.name,
			shift_work_date=str(getdate(row.shift_work_date or row.shift_start or row.time)),
			checkout_deadline=str(_cutoff(row)),
		)

	try:
		latest = _latest_in_for_checkout(employee, for_update=False)
		if latest and latest.attendance_source == "Outlet":
			_checkout_snapshot(latest)
		if latest and get_datetime(latest.time) > now:
			return block("future_in", _("Riwayat IN berada setelah waktu server. Hubungi HR."))
		is_open = bool(latest and not _has_out(latest, for_update=False))
		if is_open and now > _cutoff(latest):
			context["incomplete_session"] = {
				"checkin": latest.name, "in_time": str(latest.time), "shift": latest.shift,
				"outlet": latest.outlet_at_checkin or record.outlet,
				"shift_work_date": str(getdate(latest.shift_work_date or latest.shift_start or latest.time)),
				"checkout_deadline": str(_cutoff(latest)),
				"reason": "missing_checkout",
				"message": _("Sesi melewati batas OUT tanpa check-out. Jam OUT tetap kosong; hubungi HR melalui Attendance Request atau koreksi Attendance yang sesuai."),
			}
		if is_open and get_datetime(latest.time) <= now <= _cutoff(latest):
			use_session(latest)
			context["next_action"] = "OUT"
			return context
		configured = bool(record.outlet) and bool(
			frappe.db.get_value("Outlet", record.outlet, "enable_outlet_auto_shift")
		)
		resolution = resolve_outlet_shift(employee, now) if configured else {
			"mode": "Native", "mode_applies": False, "matched": False,
		}
		context["mode"] = resolution["mode"]
		if resolution["mode"] == "Unavailable":
			return block(resolution["code"], resolution["message"])
		if resolution["mode_applies"] and resolution["matched"]:
			values = resolution["checkin_values"]
			context.update(
				candidate_shift=values["shift"], shift_work_date=values["shift_work_date"],
				checkout_deadline=values["checkout_deadline"],
			)
		# Daily/open-session validation takes precedence over displaying an IN
		# outside its window. Expired IN remains empty; no synthetic OUT here.
		probe = frappe._dict(employee=employee, time=now, shift_work_date=context["shift_work_date"])
		try:
			validate_new_in_session(probe, for_update=False)
		except frappe.ValidationError as exc:
			frappe.clear_messages()
			if latest:
				use_session(latest)
			return block("session_complete_or_expired", str(exc), "DONE")
		if not resolution["mode_applies"]:
			return context
		if not outlet_configuration.OUTLET_AUTO_SHIFT_READY:
			return block("integration_not_ready", _("Mode shift otomatis belum dapat digunakan sampai integrasi attendance dan scheduler selesai."))
		if not resolution["matched"]:
			return block(resolution["code"], resolution["message"])
		return context
	except frappe.ValidationError as exc:
		frappe.clear_messages()
		return block("invalid_session", str(exc))
