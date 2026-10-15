# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""T06 OUT pairing tests. No persistent records, activation or attendance jobs."""

import json
import unittest
from copy import deepcopy
from datetime import datetime
from unittest.mock import patch

import frappe

from custom_hr.overrides.employee_checkin import CustomEmployeeCheckin, get_checkout_cutoff
from custom_hr.services.outlet_checkin import (
	LOCKED_FIELDS,
	OUT_COPY_FIELDS,
	_latest_in_for_checkout,
	_linked_checkout,
	prepare_or_protect_checkin,
)

MODULE = "custom_hr.services.outlet_checkin"


def locked_in():
	row = frappe._dict(
		name="IN-ORIGINAL", employee="EMP-TEST", log_type="IN", time="2026-10-15 05:04:00",
		attendance_source="Outlet", outlet_at_checkin="Original Outlet", shift="Shift 1",
		shift_work_date="2026-10-15", shift_start="2026-10-15 05:00:00", shift_end="2026-10-15 13:00:00",
		shift_actual_start="2026-10-15 00:00:00", shift_actual_end="2026-10-15 23:59:59",
		checkout_deadline="2026-10-15 23:59:59", paired_checkin=None,
		offshift=0, skip_auto_attendance=0, overtime_type=None, attendance=None,
	)
	row.shift_policy_snapshot = json.dumps({
		"version": 1, "employee": row.employee, "outlet": row.outlet_at_checkin, "shift": row.shift,
		"shift_work_date": row.shift_work_date, "shift_start": row.shift_start, "shift_end": row.shift_end,
		"checkin_start": row.shift_actual_start, "checkout_deadline": row.checkout_deadline,
		"late_entry_grace_period": 5, "early_exit_grace_period": 0, "standard_working_hours": 8,
	})
	return row


class TestOutletCheckout(unittest.TestCase):
	def setUp(self):
		self.doc = frappe.get_doc({
			"doctype": "Employee Checkin", "__islocal": 1, "employee": "EMP-TEST",
			"log_type": "OUT", "time": "2026-10-15 18:30:00",
		})
		self.employee = frappe._dict(name="EMP-TEST", status="Active", user_id=frappe.session.user, outlet="Current Outlet")
		self.entry = locked_in()
		self.hr, self.configured = True, 1
		self.linked, self.stored = None, None
		self.native_closed = False
		self.events = []
		self.query = self.mock("frappe.db.get_value", side_effect=self.read_value)
		self.latest = self.mock("_latest_in_for_checkout", side_effect=self.read_latest)
		self.duplicate = self.mock("_linked_checkout", side_effect=self.read_linked)
		self.resolver = self.mock("resolve_outlet_shift", side_effect=AssertionError("OUT must not resolve an IN shift"))
		self.mode = self.mock("get_employee_attendance_mode", return_value={"mode": "Outlet", "mode_applies": True, "message": ""})
		self.mock("is_hr_operator", side_effect=lambda: self.hr)
		self.mock("_has_out", side_effect=lambda row: self.native_closed)
		self.original_time_check = CustomEmployeeCheckin.validate_self_service_time
		self.time_check = self.method_patch("validate_self_service_time")
		self.face_check = self.method_patch("validate_face_verification")
		patcher = patch("custom_hr.hrm.doctype.outlet.outlet.OUTLET_AUTO_SHIFT_READY", False)
		patcher.start()
		self.addCleanup(patcher.stop)

	def tearDown(self):
		frappe.clear_messages()

	def mock(self, name, **kwargs):
		patcher = patch(f"{MODULE}.{name}", **kwargs)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def method_patch(self, name):
		patcher = patch.object(CustomEmployeeCheckin, name)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def read_value(self, doctype, name, fields, **kwargs):
		if doctype == "Employee":
			self.events.append("employee_lock" if kwargs.get("for_update") else "employee_read")
			return deepcopy(self.employee)
		if doctype == "Outlet":
			self.events.append("current_outlet")
			return self.configured
		if doctype == "Employee Checkin":
			return deepcopy(self.stored)
		raise AssertionError("Unexpected read: " + doctype)

	def read_latest(self, employee):
		self.events.append("latest_in")
		self.assertEqual(employee, "EMP-TEST")
		return deepcopy(self.entry)

	def read_linked(self, row):
		self.events.append("duplicate_lookup")
		self.assertEqual(row.name, self.entry.name)
		return deepcopy(self.linked)

	def snapshot(self, **changes):
		value = json.loads(self.entry.shift_policy_snapshot)
		value.update(changes)
		self.entry.shift_policy_snapshot = json.dumps(value)

	def test_out_uses_persisted_in_not_clock_or_current_shift(self):
		self.assertTrue(prepare_or_protect_checkin(self.doc))
		self.assertEqual(self.doc.paired_checkin, "IN-ORIGINAL")
		self.assertEqual(self.doc.shift, "Shift 1")
		self.assertEqual(str(self.doc.time), "2026-10-15 18:30:00")
		self.resolver.assert_not_called()
		self.mode.assert_not_called()

	def test_employee_lock_precedes_pair_and_duplicate_reads(self):
		prepare_or_protect_checkin(self.doc)
		self.assertEqual(self.events, ["employee_lock", "latest_in", "duplicate_lookup"])

	def test_all_session_fields_are_copied_from_in(self):
		prepare_or_protect_checkin(self.doc)
		for field in OUT_COPY_FIELDS:
			with self.subTest(field=field):
				actual = self.doc.get(field)
				expected = self.entry.get(field)
				if field == "shift_policy_snapshot":
					expected = json.loads(expected)
				self.assertEqual(actual, expected)

	def test_client_pair_and_snapshot_do_not_select_the_source(self):
		self.doc.update({"paired_checkin": "FOREIGN-IN", "shift": "Forged Shift", "outlet_at_checkin": "Forged Outlet", "checkout_deadline": "2026-10-16 23:59:59", "shift_policy_snapshot": {"version": 999}})
		prepare_or_protect_checkin(self.doc)
		self.assertEqual(self.doc.paired_checkin, "IN-ORIGINAL")
		self.assertEqual(self.doc.shift_policy_snapshot["version"], 1)
		self.assertEqual(self.doc.outlet_at_checkin, "Original Outlet")

	def test_mode_off_and_employee_transfer_do_not_change_out(self):
		self.employee.outlet = "Different Outlet"
		self.configured = 0
		prepare_or_protect_checkin(self.doc)
		self.assertEqual(self.doc.outlet_at_checkin, "Original Outlet")
		self.assertNotIn("current_outlet", self.events)

	def test_missing_current_outlet_does_not_break_existing_session(self):
		self.employee.outlet = None
		self.assertTrue(prepare_or_protect_checkin(self.doc))
		self.assertEqual(self.doc.shift, "Shift 1")

	def test_readiness_gate_does_not_prevent_closing_an_existing_session(self):
		self.assertTrue(prepare_or_protect_checkin(self.doc))

	def test_out_before_in_is_rejected_even_for_hr(self):
		self.doc.time = "2026-10-15 05:03:59"
		with self.assertRaisesRegex(frappe.ValidationError, "lebih awal"):
			prepare_or_protect_checkin(self.doc)

	def test_out_at_in_time_is_allowed(self):
		self.doc.time = self.entry.time
		self.assertTrue(prepare_or_protect_checkin(self.doc))

	def test_out_at_deadline_is_allowed(self):
		self.doc.time = self.entry.checkout_deadline
		self.assertTrue(prepare_or_protect_checkin(self.doc))

	def test_out_after_deadline_is_rejected_even_after_mode_disabled(self):
		self.configured = 0
		self.doc.time = "2026-10-16 00:00:00"
		with self.assertRaisesRegex(frappe.ValidationError, "Batas check-out sesi sudah lewat"):
			prepare_or_protect_checkin(self.doc)

	def test_payload_cannot_extend_original_deadline(self):
		self.doc.time = "2026-10-16 00:00:00"
		self.doc.checkout_deadline = "2026-10-16 23:59:59"
		with self.assertRaisesRegex(frappe.ValidationError, "sudah lewat"):
			prepare_or_protect_checkin(self.doc)

	def test_duplicate_out_is_rejected_even_for_hr(self):
		self.linked = frappe._dict(name="OUT-ALREADY", time="2026-10-15 13:00:00")
		with self.assertRaisesRegex(frappe.ValidationError, "sudah memiliki OUT"):
			prepare_or_protect_checkin(self.doc)

	def test_replay_after_first_out_writer_is_rejected(self):
		prepare_or_protect_checkin(self.doc)
		self.linked = frappe._dict(name="FIRST-WRITER-OUT")
		with self.assertRaisesRegex(frappe.ValidationError, "Check-out kedua"):
			prepare_or_protect_checkin(self.doc)

	def test_ignore_flags_do_not_bypass_duplicate_out(self):
		self.doc.flags.ignore_validate = self.doc.flags.ignore_checkin_restrictions = True
		self.linked = frappe._dict(name="OUT-ALREADY")
		with self.assertRaisesRegex(frappe.ValidationError, "sudah memiliki OUT"):
			self.doc.before_validate()

	def test_out_requires_own_employee_even_when_ignore_permissions_is_supplied(self):
		self.hr = False
		self.employee.user_id = "another@example.com"
		self.doc.flags.ignore_permissions = self.doc.flags.ignore_validate = True
		with self.assertRaises(frappe.PermissionError):
			self.doc.before_validate()
		self.latest.assert_not_called()

	def test_pair_from_another_employee_is_rejected(self):
		self.entry.employee = "OTHER-EMPLOYEE"
		with self.assertRaises(frappe.PermissionError):
			prepare_or_protect_checkin(self.doc)

	def test_self_service_time_and_face_checks_survive_ignore_flags(self):
		self.hr = False
		self.doc.flags.ignore_validate = self.doc.flags.ignore_checkin_restrictions = True
		self.doc.before_validate()
		self.time_check.assert_called_once()
		self.face_check.assert_called_once()

	def test_self_service_backdating_within_clock_tolerance_cannot_extend_deadline(self):
		self.doc.time = "2026-10-15 23:59:59"
		prepare_or_protect_checkin(self.doc)
		with patch("custom_hr.overrides.employee_checkin.now_datetime", return_value=datetime(2026, 10, 16)):
			with self.assertRaisesRegex(frappe.ValidationError, "menurut waktu server"):
				self.original_time_check(self.doc)

	def test_new_out_cannot_accept_attendance_from_payload(self):
		self.doc.attendance = "FORGED-ATTENDANCE"
		with self.assertRaisesRegex(frappe.ValidationError, "payload check-out"):
			prepare_or_protect_checkin(self.doc)

	def test_existing_in_attendance_is_not_used_to_claim_out_is_processed(self):
		self.entry.attendance = "EXISTING-ATTENDANCE"
		prepare_or_protect_checkin(self.doc)
		self.assertFalse(self.doc.get("attendance"))

	def test_in_skip_flag_and_overtime_are_copied_not_reenabled_by_payload(self):
		self.entry.skip_auto_attendance = 1
		self.entry.overtime_type = "Approved Type"
		self.doc.skip_auto_attendance = 0
		self.doc.overtime_type = "Forged Type"
		prepare_or_protect_checkin(self.doc)
		self.assertEqual(self.doc.skip_auto_attendance, 1)
		self.assertEqual(self.doc.overtime_type, "Approved Type")

	def test_snapshot_copy_is_independent_of_source_object(self):
		prepare_or_protect_checkin(self.doc)
		self.snapshot(late_entry_grace_period=99)
		self.assertEqual(self.doc.shift_policy_snapshot["late_entry_grace_period"], 5)

	def test_bad_snapshot_json_or_version_is_rejected_without_fallback(self):
		for value in (None, "", "invalid JSON", "[]", '{"version":999}', '{"version":true}'):
			with self.subTest(value=value), self.assertRaisesRegex(frappe.ValidationError, "Snapshot IN"):
				self.entry.shift_policy_snapshot = value
				prepare_or_protect_checkin(self.doc)
		self.resolver.assert_not_called()

	def test_snapshot_must_match_persisted_employee_shift_and_schedule(self):
		original = self.entry.shift_policy_snapshot
		for field, value in [("employee", "OTHER"), ("outlet", "OTHER"), ("shift", "OTHER"), ("shift_work_date", "2026-10-14"), ("shift_end", "2026-10-15 14:00:00"), ("checkin_start", None)]:
			with self.subTest(field=field), self.assertRaisesRegex(frappe.ValidationError, "Snapshot IN"):
				self.entry.shift_policy_snapshot = original
				self.snapshot(**{field: value})
				prepare_or_protect_checkin(self.doc)

	def test_missing_persisted_times_are_rejected(self):
		for field in ("time", "shift_actual_start", "shift_actual_end", "checkout_deadline"):
			with self.subTest(field=field), self.assertRaisesRegex(frappe.ValidationError, "Snapshot IN"):
				original = self.entry[field]
				self.entry[field] = None
				try:
					prepare_or_protect_checkin(self.doc)
				finally:
					self.entry[field] = original

	def test_no_in_in_outlet_mode_has_clear_error_without_in_resolver(self):
		self.entry = None
		with self.assertRaisesRegex(frappe.ValidationError, "Tidak ada IN outlet"):
			prepare_or_protect_checkin(self.doc)
		self.resolver.assert_not_called()

	def test_no_in_in_disabled_mode_keeps_native_route(self):
		self.entry = None
		self.configured = 0
		self.assertFalse(prepare_or_protect_checkin(self.doc))

	def test_native_open_in_can_finish_after_mode_activation(self):
		self.entry.attendance_source = None
		self.assertFalse(prepare_or_protect_checkin(self.doc))
		self.mode.assert_not_called()
		self.assertFalse(self.doc.get("paired_checkin"))

	def test_closed_native_in_is_not_reclassified_as_outlet_pair(self):
		self.entry.attendance_source = None
		self.native_closed = True
		with self.assertRaisesRegex(frappe.ValidationError, "Tidak ada IN outlet"):
			prepare_or_protect_checkin(self.doc)

	def test_native_route_cannot_accept_a_client_selected_pair(self):
		self.entry.attendance_source = None
		self.doc.paired_checkin = "FORGED-IN"
		with self.assertRaisesRegex(frappe.ValidationError, "hanya boleh ditentukan backend"):
			prepare_or_protect_checkin(self.doc)

	def test_overnight_out_keeps_previous_work_date(self):
		self.entry.time = "2026-10-15 22:09:00"
		self.entry.shift_start, self.entry.shift_end = "2026-10-15 22:00:00", "2026-10-16 06:00:00"
		self.entry.shift_actual_start = "2026-10-15 21:30:00"
		self.entry.checkout_deadline = self.entry.shift_actual_end = "2026-10-16 23:59:59"
		self.snapshot(shift_start=self.entry.shift_start, shift_end=self.entry.shift_end, checkin_start=self.entry.shift_actual_start, checkout_deadline=self.entry.checkout_deadline)
		self.doc.time = "2026-10-16 06:30:00"
		prepare_or_protect_checkin(self.doc)
		self.assertEqual(self.doc.shift_work_date, "2026-10-15")
		self.assertEqual(self.doc.checkout_deadline, "2026-10-16 23:59:59")

	def test_offset_out_timestamp_uses_site_local_deadline(self):
		self.doc.time = "2026-10-15T16:59:59Z"
		with patch("custom_hr.services.outlet_shift.get_system_timezone", return_value="Asia/Jakarta"):
			self.doc.before_validate()
		self.assertEqual(self.doc.time, datetime(2026, 10, 15, 23, 59, 59))

	def test_unsaved_out_fetch_shift_also_normalizes_offset_timestamp(self):
		self.doc.time = "2026-10-15T07:00:00Z"
		with patch("custom_hr.services.outlet_shift.get_system_timezone", return_value="Asia/Jakarta"):
			self.doc.fetch_shift()
		self.assertEqual(self.doc.time, datetime(2026, 10, 15, 14))
		self.assertEqual(self.doc.paired_checkin, "IN-ORIGINAL")

	def persist_out(self):
		prepare_or_protect_checkin(self.doc)
		self.doc.name = "OUT-PERSISTED"
		self.doc.set("__islocal", 0)
		self.stored = frappe._dict(name=self.doc.name, **{field: deepcopy(self.doc.get(field)) for field in LOCKED_FIELDS})

	def test_existing_out_fetch_and_save_guard_do_not_choose_a_new_pair(self):
		self.persist_out()
		self.latest.reset_mock()
		with patch("hrms.hr.doctype.employee_checkin.employee_checkin.EmployeeCheckin.fetch_shift") as native:
			self.doc.fetch_shift()
			native.assert_not_called()
		self.latest.assert_not_called()

	def test_existing_out_cannot_change_pair_reference(self):
		self.persist_out()
		self.doc.paired_checkin = "NEW-IN"
		self.doc.flags.ignore_validate = True
		with self.assertRaisesRegex(frappe.ValidationError, "tidak dapat diubah"):
			self.doc.before_validate()

	def test_existing_out_cannot_be_deleted_to_allow_a_second_out(self):
		self.persist_out()
		with self.assertRaisesRegex(frappe.ValidationError, "tidak boleh dihapus"):
			self.doc.on_trash()

	def test_outlet_out_does_not_enqueue_native_attendance_processor(self):
		prepare_or_protect_checkin(self.doc)
		with patch("frappe.enqueue") as enqueue:
			self.doc.queue_realtime_attendance()
			enqueue.assert_not_called()

	def test_native_out_still_queues_existing_processor(self):
		self.doc.shift = "Native Shift"
		self.doc.attendance_source = None
		self.doc.skip_auto_attendance = 0
		with patch("frappe.enqueue") as enqueue:
			self.doc.queue_realtime_attendance()
			enqueue.assert_called_once()
			self.assertEqual(enqueue.call_args.args[0], "custom_hr.overrides.employee_checkin.process_shift_attendance_now")
			self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])

	def test_cutoff_helper_prefers_locked_deadline_for_outlet(self):
		self.entry.shift_actual_end = "2026-10-16 06:00:00"
		self.assertEqual(get_checkout_cutoff(self.entry), datetime(2026, 10, 15, 23, 59, 59))


class TestCheckoutQueries(unittest.TestCase):
	def tearDown(self):
		frappe.clear_messages()

	def test_latest_in_is_a_current_read_sorted_by_time_and_name(self):
		with patch("frappe.db.sql", return_value=[]) as sql:
			self.assertIsNone(_latest_in_for_checkout("EMP-TEST"))
			query = str(sql.call_args.args[0]).upper()
			self.assertIn("FOR UPDATE", query)
			self.assertIn("ORDER BY", query)
			self.assertIn("DESC", query)
			self.assertIn("LIMIT 2", query)

	def test_duplicate_pair_query_uses_employee_and_pair_not_calendar_date(self):
		with patch("frappe.db.sql", return_value=[]) as sql:
			self.assertIsNone(_linked_checkout(locked_in()))
			query = str(sql.call_args.args[0])
			self.assertIn("FOR UPDATE", query.upper())
			self.assertIn("paired_checkin", query)
			self.assertIn("employee", query)
			self.assertNotIn("checkout_deadline", query)

	def test_tied_in_times_with_outlet_source_are_not_guessed(self):
		row, other = locked_in(), locked_in()
		other.name = "IN-OTHER"
		with patch("frappe.db.sql", return_value=[row, other]):
			with self.assertRaisesRegex(frappe.ValidationError, "beberapa IN"):
				_latest_in_for_checkout("EMP-TEST")
