# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Shared self-service writer. No commits; HTTP requests own the transaction."""

from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from uuid import UUID

import frappe
from frappe import _
from frappe.utils import now_datetime

from custom_hr.services.outlet_checkin import _employee_record, _latest_in_for_checkout

_verified_face = ContextVar("custom_hr_verified_face", default=None)
RESPONSE_FIELDS = (
	"name", "employee", "log_type", "time", "shift", "attendance_source",
	"outlet_at_checkin", "shift_work_date", "shift_start", "shift_end",
	"checkout_deadline", "paired_checkin", "face_score",
)


@contextmanager
def verified_face(employee, score):
	"""Internal proof, set only after the face matcher succeeds; never a payload flag."""
	token = _verified_face.set((employee, score))
	try:
		yield
	finally:
		_verified_face.reset(token)


def apply_verified_face(doc):
	proof = _verified_face.get()
	doc.face_verified = int(bool(proof and proof[0] == doc.employee))
	doc.face_score = proof[1] if doc.face_verified else None


def request_log_name(employee, request_id):
	if request_id is None:
		return None
	try:
		value = str(UUID(str(request_id)))
	except (ValueError, TypeError, AttributeError):
		frappe.throw(_("request_id harus berupa UUID yang valid dan digunakan ulang hanya untuk retry tindakan yang sama."))
	return "SELF-" + sha256(f"{employee}:{value}".encode()).hexdigest()


def checkin_response(doc, *, replayed=False):
	return {**{field: doc.get(field) for field in RESPONSE_FIELDS}, "replayed": replayed}


def submit_self_checkin(employee, log_type, *, latitude=None, longitude=None, request_id=None, expected_checkin=None):
	log_type = (log_type or "").upper()
	if log_type not in ("IN", "OUT"):
		frappe.throw(_("Log Type must be either IN or OUT."))
	# The account is always derived by the API, never accepted from its payload.
	record = _employee_record(employee, for_update=True)
	if record.user_id != frappe.session.user or record.status != "Active":
		frappe.throw(_("Akun harus terhubung ke karyawan aktif yang sedang login."), frappe.PermissionError)
	name = request_log_name(employee, request_id)
	if name:
		stored = frappe.db.get_value(
			"Employee Checkin", name, list(RESPONSE_FIELDS), as_dict=True, for_update=True,
		)
		if stored:
			if stored.employee != employee or stored.log_type != log_type:
				frappe.throw(_("request_id sudah digunakan untuk tindakan lain. Gunakan identitas permintaan baru."))
			return stored, True
	if expected_checkin is not None:
		# A precondition, never a client-selected pair: retries of an old OUT
		# must not close a newer IN after the employee starts another session.
		latest = _latest_in_for_checkout(employee) if log_type == "OUT" else None
		if not expected_checkin or not latest or latest.name != expected_checkin:
			frappe.throw(_("Sesi IN sudah berubah atau tidak sesuai dengan percobaan OUT ini. Muat ulang status dan hubungi HR bila hasil permintaan lama belum terkonfirmasi."))
	doc = frappe.get_doc({
		"doctype": "Employee Checkin", "employee": employee, "log_type": log_type,
		"time": now_datetime(), "latitude": latitude, "longitude": longitude,
	})
	apply_verified_face(doc)
	doc.validate_face_verification()
	doc.insert(set_name=name)
	# Read the stored values, not a candidate from an earlier camera/context call.
	stored = frappe.db.get_value(
		"Employee Checkin", doc.name, list(RESPONSE_FIELDS), as_dict=True, for_update=True,
	)
	return stored, False
