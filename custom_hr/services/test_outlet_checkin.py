# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""T05 controller/helper tests; no persistent check-in or configuration writes."""

import json
import unittest
from copy import deepcopy
from datetime import date, datetime
from unittest.mock import patch

import frappe

from custom_hr.overrides.employee_checkin import CustomEmployeeCheckin
from custom_hr.services.outlet_checkin import (
	LOCKED_FIELDS,
	SOURCE_FIELDS,
	_has_out,
	_relevant_ins,
	prepare_or_protect_checkin,
)

MODULE = "custom_hr.services.outlet_checkin"


class TestOutletCheckin(unittest.TestCase):
	def setUp(self):
		self.doc = frappe.get_doc({
			"doctype": "Employee Checkin", "__islocal": 1,
			"employee": "EMP-TEST", "log_type": "IN", "time": "2026-10-15 10:09:00",
		})
		self.employee = frappe._dict(name="EMP-TEST", status="Active", user_id=frappe.session.user, outlet="Outlet Test")
		self.hr = True
		self.configured = 1
		self.stored = None
		self.ins = []
		self.closed = False
		self.values = {
			"attendance_source": "Outlet", "outlet_at_checkin": "Outlet Test", "shift": "Shift 2",
			"shift_work_date": "2026-10-15", "shift_start": "2026-10-15 10:00:00",
			"shift_end": "2026-10-15 18:00:00", "shift_actual_start": "2026-10-15 09:30:00",
			"shift_actual_end": "2026-10-15 23:59:59", "checkout_deadline": "2026-10-15 23:59:59",
			"shift_policy_snapshot": {"version": 1, "allow_overtime": 0, "overtime_type": None, "late_entry_grace_period": 5},
		}
		self.resolution = {
			"mode": "Outlet", "mode_applies": True, "matched": True, "evaluated_at": "2026-10-15 10:09:00",
			"message": "Shift berhasil dipilih", "checkin_values": self.values,
		}
		self.value_query = self.mock("frappe.db.get_value", side_effect=self.read_value)
		self.mock("is_hr_operator", side_effect=lambda: self.hr)
		self.resolver = self.mock("resolve_outlet_shift", side_effect=lambda *args, **kwargs: deepcopy(self.resolution))
		self.mode_query = self.mock("get_employee_attendance_mode", side_effect=lambda *args, **kwargs: deepcopy(self.resolution))
		self.latest_in = self.mock("_latest_in_for_checkout", return_value=None)
		self.session_query = self.mock("_relevant_ins", side_effect=lambda *args, **kwargs: deepcopy(self.ins))
		self.out_query = self.mock("_has_out", side_effect=lambda row: self.closed)
		self.ready = patch("custom_hr.hrm.doctype.outlet.outlet.OUTLET_AUTO_SHIFT_READY", True)
		self.ready.start()
		self.addCleanup(self.ready.stop)
		self.time_check = self.patch_method("validate_self_service_time")
		self.face_check = self.patch_method("validate_face_verification")

	def tearDown(self):
		frappe.clear_messages()

	def mock(self, name, **kwargs):
		patcher = patch(f"{MODULE}.{name}", **kwargs)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def patch_method(self, name):
		patcher = patch.object(CustomEmployeeCheckin, name)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def read_value(self, doctype, name, fields, **kwargs):
		if doctype == "Employee":
			return deepcopy(self.employee)
		if doctype == "Outlet":
			return self.configured
		if doctype == "Employee Checkin":
			return deepcopy(self.stored)
		raise AssertionError("Unexpected read: " + doctype)

	def mark_persisted(self):
		self.doc.update(deepcopy(self.values))
		self.doc.name = "CK-LOCKED"
		self.doc.set("__islocal", 0)
		self.doc.offshift = self.doc.skip_auto_attendance = 0
		self.stored = frappe._dict({field: deepcopy(self.doc.get(field)) for field in LOCKED_FIELDS})
		self.stored.name = self.doc.name

	def previous_in(self, **overrides):
		return frappe._dict({
			"name": "PREVIOUS-IN", "employee": "EMP-TEST", "time": "2026-10-15 05:00:00",
			"attendance_source": "Outlet", "shift_work_date": "2026-10-15",
			"shift_start": "2026-10-15 05:00:00", "shift_actual_end": "2026-10-15 23:59:59",
			"checkout_deadline": "2026-10-15 23:59:59", **overrides,
		})

	def test_new_in_uses_resolver_without_preview_under_lock(self):
		self.assertTrue(prepare_or_protect_checkin(self.doc))
		self.resolver.assert_called_once()
		self.assertEqual(self.resolver.call_args.args[0], "EMP-TEST")
		self.assertEqual(self.resolver.call_args.kwargs, {"for_update": True})
		self.assertEqual(self.doc.shift, "Shift 2")
		self.assertEqual(self.doc.attendance_source, "Outlet")
		self.assertEqual(self.doc.outlet_at_checkin, "Outlet Test")
		self.assertEqual(self.doc.shift_policy_snapshot["version"], 1)
		self.assertEqual(self.value_query.call_args_list[0].kwargs["for_update"], True)

	def test_resolver_not_called_until_employee_identity_checked(self):
		self.hr = False
		self.employee.user_id = "other@example.com"
		with self.assertRaises(frappe.PermissionError):
			prepare_or_protect_checkin(self.doc)
		self.resolver.assert_not_called()

	def test_client_flags_do_not_bypass_identity(self):
		self.doc.flags.ignore_permissions = True
		self.doc.flags.ignore_validate = True
		self.doc.flags.ignore_checkin_restrictions = True
		self.hr = False
		self.employee.user_id = "other@example.com"
		with self.assertRaises(frappe.PermissionError):
			prepare_or_protect_checkin(self.doc)

	def test_disabled_mode_still_checks_self_service_identity(self):
		self.configured = 0
		self.hr = False
		self.employee.user_id = "other@example.com"
		with self.assertRaises(frappe.PermissionError):
			prepare_or_protect_checkin(self.doc)

	def test_hr_can_record_for_employee_but_not_double_shift(self):
		self.employee.user_id = "other@example.com"
		self.ins = [self.previous_in()]
		with self.assertRaisesRegex(frappe.ValidationError, "Double shift"):
			prepare_or_protect_checkin(self.doc)

	def test_missing_or_inactive_employee_is_rejected(self):
		self.employee.status = "Inactive"
		with self.assertRaisesRegex(frappe.ValidationError, "tidak aktif"):
			prepare_or_protect_checkin(self.doc)
		self.employee = None
		with self.assertRaisesRegex(frappe.ValidationError, "tidak ditemukan"):
			prepare_or_protect_checkin(self.doc)

	def test_disabled_mode_preserves_native_route(self):
		self.configured = 0
		self.assertFalse(prepare_or_protect_checkin(self.doc))
		self.resolver.assert_not_called()
		self.session_query.assert_called_once_with("EMP-TEST", datetime(2026, 10, 15, 10, 9), date(2026, 10, 15), outlet_only=True)

	def test_no_outlet_preserves_native_route(self):
		self.employee.outlet = None
		self.assertFalse(prepare_or_protect_checkin(self.doc))
		self.resolver.assert_not_called()

	def test_before_activation_preserves_native_route(self):
		self.resolution.update(mode="Native", mode_applies=False, matched=False)
		self.assertFalse(prepare_or_protect_checkin(self.doc))

	def test_invalid_mode_configuration_is_not_native_fallback(self):
		self.resolution.update(mode="Unavailable", mode_applies=False, matched=False, message="Invalid configuration")
		with self.assertRaisesRegex(frappe.ValidationError, "Invalid configuration"):
			prepare_or_protect_checkin(self.doc)

	def test_no_candidate_is_rejected(self):
		self.resolution.update(matched=False, message="Tidak ada kandidat")
		with self.assertRaisesRegex(frappe.ValidationError, "Tidak ada kandidat"):
			prepare_or_protect_checkin(self.doc)

	def test_readiness_gate_stays_closed_without_test_patch(self):
		with patch("custom_hr.hrm.doctype.outlet.outlet.OUTLET_AUTO_SHIFT_READY", False):
			with self.assertRaisesRegex(frappe.ValidationError, "integrasi attendance dan scheduler"):
				prepare_or_protect_checkin(self.doc)

	def test_client_supplied_outlet_snapshot_is_overwritten(self):
		self.doc.update({"attendance_source": "Forged", "shift": "Forged Shift", "outlet_at_checkin": "Forged Outlet", "shift_policy_snapshot": {"version": 999}, "paired_checkin": "FORGED-IN"})
		prepare_or_protect_checkin(self.doc)
		self.assertEqual(self.doc.shift, "Shift 2")
		self.assertEqual(self.doc.shift_policy_snapshot["version"], 1)
		self.assertEqual(self.doc.outlet_at_checkin, "Outlet Test")
		self.assertIsNone(self.doc.paired_checkin)

	def test_skip_and_offshift_are_server_controlled(self):
		self.doc.skip_auto_attendance = self.doc.offshift = 1
		self.doc.overtime_type = "Forged Overtime"
		prepare_or_protect_checkin(self.doc)
		self.assertEqual(self.doc.offshift, 0)
		self.assertEqual(self.doc.skip_auto_attendance, 0)
		self.assertIsNone(self.doc.overtime_type)

	def test_new_in_cannot_attach_attendance(self):
		self.doc.attendance = "FORGED-ATTENDANCE"
		with self.assertRaisesRegex(frappe.ValidationError, "Attendance tidak boleh"):
			prepare_or_protect_checkin(self.doc)

	def test_native_route_rejects_forged_outlet_metadata(self):
		self.configured = 0
		for field in SOURCE_FIELDS:
			with self.subTest(field=field), self.assertRaisesRegex(frappe.ValidationError, "hanya boleh ditentukan backend"):
				self.doc.set(field, "Forged")
				try:
					prepare_or_protect_checkin(self.doc)
				finally:
					self.doc.set(field, None)

	def test_time_and_face_checks_cannot_be_skipped_by_client_flags(self):
		self.hr = False
		self.doc.flags.ignore_validate = self.doc.flags.ignore_checkin_restrictions = True
		self.doc.before_validate()
		self.time_check.assert_called_once()
		self.face_check.assert_called_once()

	def test_same_work_date_blocks_even_if_previous_out_exists(self):
		self.ins, self.closed = [self.previous_in()], True
		with self.assertRaisesRegex(frappe.ValidationError, "Double shift"):
			prepare_or_protect_checkin(self.doc)
		self.out_query.assert_not_called()

	def test_native_in_on_same_shift_date_also_blocks_outlet_in(self):
		self.ins = [self.previous_in(attendance_source=None, shift_work_date=None)]
		with self.assertRaisesRegex(frappe.ValidationError, "Double shift"):
			prepare_or_protect_checkin(self.doc)

	def test_pending_previous_work_date_is_rejected_until_checkout_deadline(self):
		self.ins = [self.previous_in(time="2026-10-14 22:00:00", shift_work_date="2026-10-14", shift_start="2026-10-14 22:00:00")]
		with self.assertRaisesRegex(frappe.ValidationError, "check-in terbuka"):
			prepare_or_protect_checkin(self.doc)

	def test_closed_previous_work_date_allows_new_in(self):
		self.ins, self.closed = [self.previous_in(time="2026-10-14 22:00:00", shift_work_date="2026-10-14", shift_start="2026-10-14 22:00:00")], True
		self.assertTrue(prepare_or_protect_checkin(self.doc))

	def test_expired_previous_work_date_allows_new_in(self):
		self.ins = [self.previous_in(time="2026-10-14 05:00:00", shift_work_date="2026-10-14", shift_start="2026-10-14 05:00:00", checkout_deadline="2026-10-14 23:59:59")]
		self.assertTrue(prepare_or_protect_checkin(self.doc))

	def test_replay_after_first_writer_is_rejected(self):
		prepare_or_protect_checkin(self.doc)
		self.ins = [self.previous_in(time="2026-10-15 10:09:00")]
		with self.assertRaisesRegex(frappe.ValidationError, "Double shift"):
			prepare_or_protect_checkin(self.doc)

	def test_disabling_mode_does_not_allow_second_outlet_session(self):
		self.configured = 0
		self.ins = [self.previous_in()]
		with self.assertRaisesRegex(frappe.ValidationError, "Double shift"):
			prepare_or_protect_checkin(self.doc)

	def test_repeated_preparation_of_unsaved_in_is_safe(self):
		prepare_or_protect_checkin(self.doc)
		before = {field: deepcopy(self.doc.get(field)) for field in LOCKED_FIELDS}
		prepare_or_protect_checkin(self.doc)
		self.assertEqual({field: self.doc.get(field) for field in LOCKED_FIELDS}, before)

	def test_before_validate_normalizes_offset_timestamp_before_resolution(self):
		self.doc.time = "2026-10-15T03:09:00Z"
		with patch("custom_hr.services.outlet_shift.get_system_timezone", return_value="Asia/Jakarta"):
			self.doc.before_validate()
		self.assertEqual(self.resolver.call_args.args[1], datetime(2026, 10, 15, 10, 9))

	def test_existing_snapshot_is_not_resolved_after_mode_or_outlet_changes(self):
		self.mark_persisted()
		self.configured = 0
		self.employee.outlet = "New Outlet"
		self.assertTrue(prepare_or_protect_checkin(self.doc))
		self.resolver.assert_not_called()
		self.assertEqual(self.doc.outlet_at_checkin, "Outlet Test")

	def test_all_locked_fields_are_immutable_even_with_ignore_flags(self):
		self.mark_persisted()
		self.doc.flags.ignore_validate = self.doc.flags.ignore_checkin_restrictions = True
		for field in LOCKED_FIELDS:
			with self.subTest(field=field), self.assertRaisesRegex(frappe.ValidationError, "tidak dapat diubah"):
				original = deepcopy(self.doc.get(field))
				if field in {"offshift", "skip_auto_attendance"}:
					value = 1
				elif field == "shift_policy_snapshot":
					value = {"version": 999}
				else:
					value = "FORGED"
				self.doc.set(field, value)
				try:
					self.doc.before_validate()
				finally:
					self.doc.set(field, original)

	def test_json_and_datetime_roundtrip_does_not_trigger_false_change(self):
		self.mark_persisted()
		self.stored.time = datetime(2026, 10, 15, 10, 9)
		self.stored.shift_work_date = date(2026, 10, 15)
		self.stored.shift_policy_snapshot = json.dumps(self.doc.shift_policy_snapshot, sort_keys=True)
		self.assertTrue(prepare_or_protect_checkin(self.doc))

	def test_native_existing_log_cannot_be_reclassified_as_outlet(self):
		self.mark_persisted()
		self.stored.attendance_source = None
		with self.assertRaisesRegex(frappe.ValidationError, "attendance_source"):
			prepare_or_protect_checkin(self.doc)

	def test_non_snapshot_fields_can_still_change(self):
		self.mark_persisted()
		self.doc.device_id = "Updated device note"
		self.assertTrue(prepare_or_protect_checkin(self.doc))

	def test_fetch_shift_on_locked_log_does_not_call_native_or_resolver(self):
		self.mark_persisted()
		with patch("hrms.hr.doctype.employee_checkin.employee_checkin.EmployeeCheckin.fetch_shift") as native:
			self.doc.fetch_shift()
			native.assert_not_called()
		self.resolver.assert_not_called()

	def test_fetch_shift_native_route_is_preserved(self):
		self.configured = 0
		with patch("hrms.hr.doctype.employee_checkin.employee_checkin.EmployeeCheckin.fetch_shift") as native:
			self.doc.fetch_shift()
			native.assert_called_once()

	def test_locked_in_can_be_deleted_so_attendance_can_be_retried(self):
		# Deliberately open: HR/admins must be able to remove outlet logs to repeat a test
		# session. Frappe's own link check still orders deletes (Attendance, then OUT, then IN).
		self.assertNotIn("on_trash", vars(CustomEmployeeCheckin))

	def test_existing_record_is_read_with_row_lock_not_client_original(self):
		self.mark_persisted()
		self.doc._doc_before_save = frappe._dict(attendance_source="Forged")
		prepare_or_protect_checkin(self.doc)
		self.assertEqual(self.value_query.call_args_list[0].args[0], "Employee Checkin")
		self.assertTrue(self.value_query.call_args_list[0].kwargs["for_update"])

	def test_out_route_requires_in_without_running_in_resolver(self):
		self.doc.log_type = "OUT"
		with self.assertRaisesRegex(frappe.ValidationError, "Tidak ada IN outlet"):
			prepare_or_protect_checkin(self.doc)
		self.resolver.assert_not_called()

	def test_native_out_route_stays_native_if_no_pending_outlet_in(self):
		self.doc.log_type = "OUT"
		self.configured = 0
		self.assertFalse(prepare_or_protect_checkin(self.doc))

	def test_native_out_rejects_client_selected_outlet_pair(self):
		self.doc.log_type = "OUT"
		self.configured = 0
		self.doc.paired_checkin = "FORGED-IN"
		with self.assertRaisesRegex(frappe.ValidationError, "hanya boleh ditentukan backend"):
			prepare_or_protect_checkin(self.doc)


class TestOutletSessionQueries(unittest.TestCase):
	def test_resolver_write_path_locks_shift_definitions_in_name_order(self):
		from custom_hr.services.outlet_shift import resolve_outlet_shift

		context = {"employee": "EMP-TEST", "mode": "Outlet", "mode_applies": True, "mode_reason": "outlet_mode", "message": "", "evaluated_at": "2026-10-15 10:00:00"}
		outlet = frappe._dict(holiday_list="Outlet", shifts=[frappe._dict(shift_type="Shift A", enabled=1)])
		with (
			patch("custom_hr.services.outlet_shift._read_context", return_value=(context, outlet)) as read_context,
			patch("frappe.db.sql", return_value=[]) as sql,
		):
			resolve_outlet_shift("EMP-TEST", "2026-10-15 10:00:00", for_update=True)
			query = str(sql.call_args.args[0])
			self.assertIn("FOR UPDATE", query.upper())
			self.assertIn("ORDER BY", query.upper())
			self.assertIn("Shift Type", query)
			read_context.assert_called_once_with("EMP-TEST", "2026-10-15 10:00:00", for_update=True)

	def test_session_history_uses_current_locking_read(self):
		with patch("frappe.db.sql", return_value=[]) as sql:
			_relevant_ins("EMP-TEST", datetime(2026, 10, 15, 10), date(2026, 10, 15), outlet_only=False)
			query = str(sql.call_args.args[0])
			self.assertIn("FOR UPDATE", query.upper())
			self.assertIn("Employee Checkin", query)

	def test_out_check_uses_explicit_pair_and_current_locking_read(self):
		row = frappe._dict(name="IN-TEST", employee="EMP-TEST", attendance_source="Outlet", time="2026-10-15 05:00:00", checkout_deadline="2026-10-15 23:59:59")
		with patch("frappe.db.sql", return_value=[]) as sql:
			self.assertFalse(_has_out(row))
			query = str(sql.call_args.args[0])
			self.assertIn("FOR UPDATE", query.upper())
			self.assertIn("paired_checkin", query)
