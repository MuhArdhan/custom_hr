# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""T07 API/context/proof/retry tests; no persistent business writes."""

import unittest
from copy import deepcopy
from datetime import datetime
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.api import checkin, face
from custom_hr.overrides.employee_checkin import CustomEmployeeCheckin
from custom_hr.services import checkin_submission as submission
from custom_hr.services.outlet_checkin import _has_out, _latest_in_for_checkout, _relevant_ins
from custom_hr.services.test_outlet_checkout import locked_in

NOW = datetime(2026, 10, 15, 10)
REQUEST_ID = "d288162e-b86c-443d-801d-5ccf98d92d84"


class CheckinTestCase(unittest.TestCase):
	def mock(self, target, **kwargs):
		patcher = patch(target, **kwargs)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def tearDown(self):
		frappe.clear_messages()


class TestCheckinContext(CheckinTestCase):
	def setUp(self):
		self.entry = None
		self.closed = False
		self.employee = frappe._dict(name="EMP-TEST", status="Active", user_id=frappe.session.user, outlet="Current Outlet")
		self.resolution = {
			"mode": "Outlet", "mode_applies": True, "matched": True, "code": "matched", "message": "ok",
			"checkin_values": {"shift": "Shift 2", "shift_work_date": "2026-10-15", "checkout_deadline": "2026-10-15 23:59:59"},
		}
		root = "custom_hr.api.checkin."
		self.mock(root + "get_current_employee", return_value="EMP-TEST")
		self.employee_read = self.mock(root + "_employee_record", side_effect=lambda *a, **k: self.employee)
		self.mock(root + "now_datetime", return_value=NOW)
		self.mock(root + "frappe.db.get_value", return_value=1)
		self.latest = self.mock(root + "_latest_in_for_checkout", side_effect=lambda *a, **k: deepcopy(self.entry))
		self.has_out = self.mock(root + "_has_out", side_effect=lambda *a, **k: self.closed)
		self.resolver = self.mock(root + "resolve_outlet_shift", side_effect=lambda *a, **k: deepcopy(self.resolution))
		self.session = self.mock(root + "validate_new_in_session")
		self.mock("custom_hr.hrm.doctype.outlet.outlet.OUTLET_AUTO_SHIFT_READY", new=True)

	def test_new_session_returns_server_evaluated_candidate(self):
		result = checkin.get_checkin_context()
		self.assertEqual(result["next_action"], "IN")
		self.assertTrue(result["allowed"])
		self.assertEqual(result["candidate_shift"], "Shift 2")
		self.assertEqual(result["server_time"], str(NOW))
		self.assertEqual(result["checkout_deadline"], "2026-10-15 23:59:59")
		self.resolver.assert_called_once_with("EMP-TEST", NOW)

	def test_context_reads_sessions_without_locks_or_writes(self):
		with patch("frappe.db.sql") as sql, patch("frappe.get_doc") as writer:
			checkin.get_checkin_context()
			sql.assert_not_called()
			writer.assert_not_called()
		self.employee_read.assert_called_once_with("EMP-TEST", for_update=False)
		self.latest.assert_called_once_with("EMP-TEST", for_update=False)
		self.assertFalse(self.session.call_args.kwargs["for_update"])

	def test_open_outlet_session_returns_out_and_locked_outlet(self):
		self.entry = locked_in()
		result = checkin.get_checkin_context()
		self.assertEqual(result["next_action"], "OUT")
		self.assertEqual(result["outlet"], "Original Outlet")
		self.assertEqual(result["candidate_shift"], "Shift 1")
		self.assertEqual(result["paired_checkin"], "IN-ORIGINAL")
		self.resolver.assert_not_called()

	def test_existing_session_out_survives_readiness_off(self):
		self.entry = locked_in()
		with patch("custom_hr.hrm.doctype.outlet.outlet.OUTLET_AUTO_SHIFT_READY", False):
			self.assertTrue(checkin.get_checkin_context()["allowed"])

	def test_completed_today_returns_done(self):
		self.entry, self.closed = locked_in(), True
		self.session.side_effect = frappe.ValidationError("Sudah check-in")
		result = checkin.get_checkin_context()
		self.assertEqual(result["next_action"], "DONE")
		self.assertFalse(result["allowed"])
		self.assertEqual(result["candidate_shift"], "Shift 1")

	def test_completed_at_deadline_returns_done_without_fabricated_out(self):
		self.entry = locked_in()
		self.mock("custom_hr.api.checkin.now_datetime", return_value=datetime(2026, 10, 15, 23, 59, 59))
		self.closed = True
		self.session.side_effect = frappe.ValidationError("Sudah check-in")
		self.assertEqual(checkin.get_checkin_context()["next_action"], "DONE")

	def test_previous_expired_session_allows_new_work_date(self):
		self.entry = locked_in()
		self.entry.time = "2026-10-14 05:04:00"
		self.entry.attendance_source = None
		self.entry.shift_actual_end = "2026-10-14 23:59:59"
		result = checkin.get_checkin_context()
		self.assertEqual(result["next_action"], "IN")
		self.assertEqual(result["incomplete_session"]["reason"], "missing_checkout")
		self.assertEqual(result["incomplete_session"]["checkin"], "IN-ORIGINAL")

	def test_no_candidate_has_clear_reason(self):
		self.resolution.update(matched=False, code="outside_checkin_window", message="Tidak ada shift")
		result = checkin.get_checkin_context()
		self.assertFalse(result["allowed"])
		self.assertEqual(result["reason"], "outside_checkin_window")

	def test_ambiguous_candidate_is_not_guessed(self):
		self.resolution.update(matched=False, code="ambiguous_candidate", message="Ambigu")
		self.assertEqual(checkin.get_checkin_context()["reason"], "ambiguous_candidate")

	def test_gate_blocks_new_outlet_in(self):
		with patch("custom_hr.hrm.doctype.outlet.outlet.OUTLET_AUTO_SHIFT_READY", False):
			result = checkin.get_checkin_context()
		self.assertEqual(result["reason"], "integration_not_ready")
		self.assertFalse(result["allowed"])

	def test_native_mode_not_misrepresented_as_outlet(self):
		self.resolution.update(mode="Native", mode_applies=False)
		result = checkin.get_checkin_context()
		self.assertEqual(result["mode"], "Native")
		self.assertIsNone(result["candidate_shift"])

	def test_native_open_session_returns_out(self):
		self.entry = locked_in()
		self.entry.attendance_source = None
		self.assertEqual(checkin.get_checkin_context()["next_action"], "OUT")
		self.resolver.assert_not_called()

	def test_invalid_mode_returns_failure(self):
		self.resolution.update(mode="Unavailable", code="outlet_inactive", message="Outlet nonaktif")
		self.assertEqual(checkin.get_checkin_context()["reason"], "outlet_inactive")

	def test_invalid_snapshot_blocks_without_master_fallback(self):
		self.entry = locked_in()
		self.entry.shift_policy_snapshot = "invalid"
		self.assertEqual(checkin.get_checkin_context()["reason"], "invalid_session")
		self.resolver.assert_not_called()

	def test_tied_in_error_is_explained(self):
		self.latest.side_effect = frappe.ValidationError("Beberapa IN")
		self.assertEqual(checkin.get_checkin_context()["reason"], "invalid_session")

	def test_context_requires_own_active_employee_even_for_hr(self):
		for field, value in (("user_id", "foreign@example.com"), ("status", "Left")):
			original = self.employee[field]
			self.employee[field] = value
			with self.subTest(field=field), self.assertRaises(frappe.PermissionError):
				checkin.get_checkin_context()
			self.employee[field] = original

	def test_context_does_not_accept_employee_or_client_time(self):
		with self.assertRaises(TypeError):
			checkin.get_checkin_context(employee="OTHER", time="2026-10-15 05:00:00")


class TestSharedSubmission(CheckinTestCase):
	def setUp(self):
		self.employee = frappe._dict(name="EMP-TEST", status="Active", user_id=frappe.session.user)
		self.stored = None
		self.events = []
		root = "custom_hr.services.checkin_submission."
		self.lock = self.mock(root + "_employee_record", side_effect=lambda *a, **k: self.events.append("lock") or self.employee)
		self.mock(root + "now_datetime", side_effect=lambda: self.events.append("clock") or NOW)
		self.doc = MagicMock()
		self.doc.name = "SAVED-LOG"
		self.writer = self.mock(root + "frappe.get_doc", return_value=self.doc)
		self.query = self.mock(root + "frappe.db.get_value", side_effect=lambda *a, **k: self.stored)

	def test_server_time_taken_after_employee_lock(self):
		submission.submit_self_checkin("EMP-TEST", "IN")
		self.assertEqual(self.events, ["lock", "clock"])
		self.assertEqual(self.writer.call_args.args[0]["time"], NOW)
		self.doc.insert.assert_called_once_with(set_name=None)

	def test_retry_returns_saved_log_without_insert_or_recompute(self):
		self.stored = frappe._dict(employee="EMP-TEST", log_type="IN", shift="Original Shift", name="SAVED")
		result, replayed = submission.submit_self_checkin("EMP-TEST", "IN", request_id=REQUEST_ID)
		self.assertTrue(replayed)
		self.assertEqual(result.shift, "Original Shift")
		self.writer.assert_not_called()
		self.assertEqual(self.events, ["lock"])
		self.assertTrue(self.query.call_args.kwargs["for_update"])

	def test_request_id_reuse_for_different_action_rejected(self):
		self.stored = frappe._dict(employee="EMP-TEST", log_type="IN")
		with self.assertRaisesRegex(frappe.ValidationError, "tindakan lain"):
			submission.submit_self_checkin("EMP-TEST", "OUT", request_id=REQUEST_ID)

	def test_foreign_or_inactive_account_cannot_submit(self):
		self.employee.user_id = "OTHER"
		with self.assertRaises(frappe.PermissionError):
			submission.submit_self_checkin("EMP-TEST", "IN")
		self.writer.assert_not_called()

	def test_response_uses_database_stored_shift(self):
		self.stored = frappe._dict(name="SAVED-LOG", shift="Actually Stored", employee="EMP-TEST", log_type="IN")
		result, replayed = submission.submit_self_checkin("EMP-TEST", "IN")
		self.assertFalse(replayed)
		self.assertEqual(submission.checkin_response(result)["shift"], "Actually Stored")

	def test_nonface_endpoint_never_accepts_face_flag_or_employee(self):
		with self.assertRaises(TypeError):
			checkin.submit_checkin("IN", face_verified=1)
		with self.assertRaises(TypeError):
			checkin.submit_checkin("IN", employee="OTHER")

	def test_normal_endpoint_calls_shared_writer_with_current_employee(self):
		with patch.object(checkin, "get_current_employee", return_value="EMP-TEST"), patch.object(checkin, "submit_self_checkin", return_value=(frappe._dict(shift="Saved"), False)) as writer:
			result = checkin.submit_checkin("IN", request_id=REQUEST_ID)
		self.assertEqual(result["shift"], "Saved")
		self.assertEqual(writer.call_args.args, ("EMP-TEST", "IN"))

	def test_request_names_are_stable_scoped_and_uuid_validated(self):
		name = submission.request_log_name("EMP-TEST", REQUEST_ID)
		self.assertEqual(name, submission.request_log_name("EMP-TEST", REQUEST_ID.upper()))
		self.assertNotEqual(name, submission.request_log_name("OTHER", REQUEST_ID))
		self.assertTrue(name.startswith("SELF-"))
		self.assertIsNone(submission.request_log_name("EMP-TEST", None))
		for value in ("", "arbitrary", {}, 123):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				submission.request_log_name("EMP-TEST", value)

	def test_invalid_log_type_rejected_before_write(self):
		with self.assertRaises(frappe.ValidationError):
			submission.submit_self_checkin("EMP-TEST", "DONE")
		self.lock.assert_not_called()

	def test_uuid_does_not_bypass_face_requirement_for_new_write(self):
		self.doc.validate_face_verification.side_effect = frappe.ValidationError("Face required")
		with self.assertRaises(frappe.ValidationError):
			submission.submit_self_checkin("EMP-TEST", "IN", request_id=REQUEST_ID)
		self.doc.insert.assert_not_called()


class TestFaceProofAndLifecycle(CheckinTestCase):
	def test_face_descriptor_rejects_nonfinite_and_nonnumeric_values(self):
		for value in (float("nan"), float("inf"), "NaN", None, "invalid"):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				face._validate_descriptor([value] * 128)

	def test_face_descriptor_requires_full_vector(self):
		for value in ([], [0.0], "not-json", {}):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				face._validate_descriptor(value)

	def test_face_descriptor_accepts_valid_finite_json(self):
		self.assertEqual(face._validate_descriptor("[" + ",".join(["0"] * 128) + "]"), [0.0] * 128)

	def test_payload_face_verified_is_cleared_without_internal_proof(self):
		doc = frappe._dict(employee="EMP-TEST", face_verified=1, face_score=0.01)
		submission.apply_verified_face(doc)
		self.assertEqual(doc.face_verified, 0)
		self.assertIsNone(doc.face_score)

	def test_proof_is_employee_scoped_and_reset_after_exception(self):
		doc = frappe._dict(employee="EMP-TEST")
		with self.assertRaises(RuntimeError):
			with submission.verified_face("EMP-TEST", 0.12):
				submission.apply_verified_face(doc)
				self.assertEqual(doc.face_verified, 1)
				self.assertEqual(doc.face_score, 0.12)
				raise RuntimeError()
		submission.apply_verified_face(doc)
		self.assertEqual(doc.face_verified, 0)
		with submission.verified_face("OTHER", 0.01):
			submission.apply_verified_face(doc)
			self.assertEqual(doc.face_verified, 0)

	def test_raw_api_self_service_ignores_device_time_face_flag_and_ignore_flags(self):
		doc = frappe.get_doc({"doctype": "Employee Checkin", "employee": "EMP-TEST", "log_type": "IN", "time": "2000-01-01", "face_verified": 1})
		doc.flags.ignore_validate = doc.flags.ignore_checkin_restrictions = True
		with patch("frappe.get_roles", return_value=[]), patch.dict(frappe.session, user="employee@example.com"), patch("custom_hr.overrides.employee_checkin._employee_record") as lock, patch("custom_hr.overrides.employee_checkin.now_datetime", return_value=NOW), patch("custom_hr.overrides.employee_checkin.prepare_or_protect_checkin", return_value=False), patch.object(CustomEmployeeCheckin, "validate_self_service_time"), patch.object(CustomEmployeeCheckin, "validate_daily_checkin_limit"), patch.object(CustomEmployeeCheckin, "validate_checkout_window"), patch.object(CustomEmployeeCheckin, "validate_face_verification") as face_check:
			doc.before_validate()
		self.assertEqual(doc.time, NOW)
		self.assertEqual(doc.face_verified, 0)
		lock.assert_called_once_with("EMP-TEST", for_update=True)
		face_check.assert_called_once()

	def test_hr_historical_document_time_preserved(self):
		doc = frappe.get_doc({"doctype": "Employee Checkin", "employee": "EMP-TEST", "log_type": "IN", "time": "2026-10-14 05:00:00"})
		with patch("custom_hr.overrides.employee_checkin.prepare_or_protect_checkin", return_value=True):
			doc.before_validate()
		self.assertEqual(doc.time, datetime(2026, 10, 14, 5))

	def test_face_endpoint_uses_shared_writer_and_returns_stored_shift(self):
		stored = frappe._dict(name="SAVED", employee="EMP-TEST", shift="Stored Shift", log_type="IN", face_score=0)
		def shared(employee, log_type, **kwargs):
			proof_doc = frappe._dict(employee=employee)
			submission.apply_verified_face(proof_doc)
			self.assertEqual(proof_doc.face_verified, 1)
			self.assertEqual(kwargs["request_id"], REQUEST_ID)
			return stored, True
		with patch.object(face, "get_current_employee", return_value="EMP-TEST"), patch.object(face, "validate_active_employee"), patch.object(face, "_validate_descriptor", return_value=[0.0]), patch("frappe.db.get_value", return_value=frappe._dict(name="PROFILE", descriptor="[0.0]")), patch("frappe.db.get_single_value", return_value=0.5), patch.object(face, "submit_self_checkin", side_effect=shared), patch.object(face, "_save_photo_data_url") as photo, patch("frappe.db.commit") as commit:
			result = face.face_checkin("IN", [0.0], photo="photo", request_id=REQUEST_ID)
		self.assertEqual(result["shift"], "Stored Shift")
		self.assertTrue(result["replayed"])
		photo.assert_not_called()
		commit.assert_not_called()

	def test_context_query_helpers_can_run_without_for_update(self):
		with patch("frappe.db.sql", return_value=[]) as sql:
			_latest_in_for_checkout("EMP-TEST", for_update=False)
			self.assertNotIn("FOR UPDATE", str(sql.call_args.args[0]).upper())
			_has_out(locked_in(), for_update=False)
			self.assertNotIn("FOR UPDATE", str(sql.call_args.args[0]).upper())
			_relevant_ins("EMP-TEST", NOW, NOW.date(), outlet_only=False, for_update=False)
			self.assertNotIn("FOR UPDATE", str(sql.call_args.args[0]).upper())

	def test_native_daily_check_uses_current_read_and_exclusive_next_midnight(self):
		doc = frappe.get_doc({"doctype": "Employee Checkin", "employee": "EMP-TEST", "log_type": "IN", "time": NOW})
		with patch("frappe.db.sql", return_value=[]) as sql:
			doc.validate_daily_checkin_limit()
			query = str(sql.call_args.args[0]).upper()
			self.assertIn("FOR UPDATE", query)
			self.assertNotIn("BETWEEN", query)
			self.assertIn("<", query)

	def test_native_checkout_uses_current_read_for_last_log(self):
		doc = frappe.get_doc({"doctype": "Employee Checkin", "employee": "EMP-TEST", "log_type": "OUT", "time": NOW})
		with patch("frappe.db.sql", return_value=[]) as sql:
			with self.assertRaises(frappe.ValidationError):
				doc.validate_checkout_window()
			self.assertIn("FOR UPDATE", str(sql.call_args.args[0]).upper())
