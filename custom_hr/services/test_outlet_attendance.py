# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""T08 calculation, pair-scoped persistence, locking and job-boundary tests."""

import json
import unittest
from copy import deepcopy
from datetime import datetime
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.services import outlet_attendance as service
from custom_hr.services.test_outlet_checkout import locked_in

MODULE = "custom_hr.services.outlet_attendance"


def session():
	entry = locked_in()
	policy = json.loads(entry.shift_policy_snapshot)
	policy.update(
		attendance_source="Outlet", company="Original Company", holiday_source="Outlet", holiday_list="Outlet Holidays",
		enable_auto_attendance=0, enable_late_entry_marking=1, enable_early_exit_marking=1,
		mark_auto_attendance_on_holidays=0, allow_overtime=0, overtime_type=None,
		working_hours_threshold_for_half_day=0, working_hours_threshold_for_absent=0,
		determine_check_in_and_check_out="Strictly based on Log Type in Employee Checkin",
		working_hours_calculation_based_on="First Check-in and Last Check-out",
		missing_checkout_status="Present", missing_checkout_hours_source="Locked Shift Allocation",
	)
	entry.shift_policy_snapshot = json.dumps(policy)
	checkout = deepcopy(entry)
	checkout.update(name="OUT-ORIGINAL", log_type="OUT", paired_checkin=entry.name, time="2026-10-15 13:00:00")
	return entry, checkout


class TestCase(unittest.TestCase):
	def mock(self, name, **kwargs):
		patcher = patch(f"{MODULE}.{name}", **kwargs)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def tearDown(self):
		frappe.clear_messages()


class TestAttendanceCalculation(TestCase):
	def setUp(self):
		self.entry, self.out = session()

	def policy(self, **changes):
		value = json.loads(self.entry.shift_policy_snapshot)
		value.update(changes)
		self.entry.shift_policy_snapshot = self.out.shift_policy_snapshot = json.dumps(value)

	def calculate(self, **kwargs):
		return service.calculate_session_attendance(self.entry, self.out, **kwargs)

	def test_complete_pair_uses_actual_duration_and_original_company(self):
		values = self.calculate()
		self.assertEqual(values.working_hours, 7.93)
		self.assertEqual(values.status, "Present")
		self.assertEqual(values.company, "Original Company")
		self.assertEqual(values.working_hours_source, "Actual Logs")
		self.assertEqual(values.missing_checkout, 0)

	def test_present_short_pair_when_thresholds_are_zero(self):
		self.out.time = "2026-10-15 05:05:00"
		self.assertEqual(self.calculate().status, "Present")

	def test_zero_duration_pair_does_not_become_absent_without_threshold(self):
		self.out.time = self.entry.time
		self.assertEqual(self.calculate().working_hours, 0)
		self.assertEqual(self.calculate().status, "Present")

	def test_late_boundary_is_inclusive(self):
		for stamp, expected in (("2026-10-15 05:05:00", 0), ("2026-10-15 05:05:01", 1)):
			self.entry.time = stamp
			with self.subTest(stamp=stamp):
				self.assertEqual(self.calculate().late_entry, expected)

	def test_grace_is_configurable_not_hardcoded(self):
		self.policy(late_entry_grace_period=15)
		self.entry.time = "2026-10-15 05:14:00"
		self.assertEqual(self.calculate().late_entry, 0)

	def test_early_exit_zero_grace_uses_scheduled_end(self):
		self.out.time = "2026-10-15 12:59:59"
		self.assertEqual(self.calculate().early_exit, 1)
		self.out.time = "2026-10-15 13:00:00"
		self.assertEqual(self.calculate().early_exit, 0)

	def test_early_grace_and_marking_flags_are_respected(self):
		self.policy(early_exit_grace_period=10)
		self.out.time = "2026-10-15 12:50:00"
		self.assertEqual(self.calculate().early_exit, 0)
		self.policy(enable_late_entry_marking=0, enable_early_exit_marking=0)
		self.entry.time, self.out.time = "2026-10-15 06:00:00", "2026-10-15 12:00:00"
		self.assertEqual((self.calculate().late_entry, self.calculate().early_exit), (0, 0))

	def test_thresholds_determine_absent_half_day_present(self):
		self.policy(working_hours_threshold_for_absent=4, working_hours_threshold_for_half_day=6)
		self.entry.time = "2026-10-15 05:00:00"
		for stamp, expected in (("08:59:00", "Absent"), ("09:00:00", "Half Day"), ("11:00:00", "Present")):
			self.out.time = "2026-10-15 " + stamp
			with self.subTest(stamp=stamp):
				self.assertEqual(self.calculate().status, expected)

	def test_half_holiday_halves_both_thresholds(self):
		self.policy(working_hours_threshold_for_absent=4, working_hours_threshold_for_half_day=6)
		self.entry.time, self.out.time = "2026-10-15 05:00:00", "2026-10-15 08:00:00"
		self.assertEqual(self.calculate().status, "Absent")
		self.assertEqual(self.calculate(half_holiday=True).status, "Present")

	def test_overnight_attendance_date_is_shift_start_date(self):
		for row in (self.entry, self.out):
			row.shift_start, row.shift_end = "2026-10-15 22:00:00", "2026-10-16 06:00:00"
			row.shift_actual_start = "2026-10-15 00:00:00"
			row.checkout_deadline = row.shift_actual_end = "2026-10-16 23:59:59"
		self.entry.time, self.out.time = "2026-10-15 22:00:00", "2026-10-16 06:00:00"
		self.policy(shift_start=self.entry.shift_start, shift_end=self.entry.shift_end, checkout_deadline=self.entry.checkout_deadline)
		values = self.calculate()
		self.assertEqual(str(values.attendance_date), "2026-10-15")
		self.assertEqual(values.working_hours, 8)

	def test_out_after_shift_end_counts_actual_hours_not_capped_schedule(self):
		self.out.time = "2026-10-15 18:00:00"
		self.assertEqual(self.calculate().working_hours, 12.93)
		self.assertEqual(self.calculate().actual_overtime_duration, 0)

	def test_overtime_uses_snapshot_not_master_and_requires_complete_pair(self):
		self.policy(allow_overtime=1, overtime_type="Approved Type")
		self.out.time = "2026-10-15 15:04:00"
		values = self.calculate()
		self.assertEqual(values.actual_overtime_duration, 2)
		self.assertEqual(values.overtime_type, "Approved Type")

	def test_missing_out_before_or_exact_deadline_is_rejected(self):
		for stamp in ("2026-10-15 13:00:00", "2026-10-15 23:59:59"):
			with self.subTest(stamp=stamp), self.assertRaises(frappe.ValidationError):
				service.calculate_session_attendance(self.entry, finalize_missing=True, now=stamp)

	def test_missing_out_requires_explicit_finalization(self):
		with self.assertRaises(frappe.ValidationError):
			service.calculate_session_attendance(self.entry, now="2026-10-16 00:00:00")

	def test_missing_out_allocates_locked_hours_without_out_early_exit_or_overtime(self):
		self.entry.time = "2026-10-15 12:00:00"
		self.policy(allow_overtime=1, overtime_type="Type", working_hours_threshold_for_absent=10)
		values = service.calculate_session_attendance(self.entry, finalize_missing=True, now="2026-10-16 00:00:00")
		self.assertEqual(values.status, "Present")
		self.assertEqual(values.working_hours, 8)
		self.assertEqual(values.working_hours_source, "Locked Shift Allocation")
		self.assertEqual(values.missing_checkout, 1)
		self.assertEqual(values.late_entry, 1)
		self.assertEqual(values.early_exit, 0)
		self.assertIsNone(values.out_time)
		self.assertIsNone(values.source_checkout)
		self.assertIsNone(values.overtime_type)
		self.assertEqual(values.actual_overtime_duration, 0)

	def test_invalid_or_incomplete_snapshot_never_falls_back_to_master(self):
		for changes in ({"standard_working_hours": 99}, {"holiday_source": "Employee"}, {"late_entry_grace_period": -1}):
			self.entry, self.out = session()
			self.policy(**changes)
			with self.subTest(changes=changes), self.assertRaises(frappe.ValidationError):
				self.calculate()

	def test_missing_policy_field_is_rejected(self):
		policy = json.loads(self.entry.shift_policy_snapshot)
		policy.pop("enable_late_entry_marking")
		self.entry.shift_policy_snapshot = self.out.shift_policy_snapshot = json.dumps(policy)
		with self.assertRaises(frappe.ValidationError):
			self.calculate()

	def test_foreign_pair_or_changed_schedule_is_rejected(self):
		for field, value in (("employee", "OTHER"), ("paired_checkin", "OTHER-IN"), ("shift", "OTHER-SHIFT"), ("log_type", "IN"), ("shift_policy_snapshot", "{}")):
			self.entry, self.out = session()
			self.out[field] = value
			with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
				self.calculate()

	def test_invalid_out_times_rejected(self):
		for value in (None, "2026-10-15 05:03:59", "2026-10-16 00:00:00"):
			self.out.time = value
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				self.calculate()

	def test_calculation_does_not_mutate_original_logs(self):
		before = deepcopy((self.entry, self.out))
		self.calculate()
		self.assertEqual((self.entry, self.out), before)

	def test_explicit_employee_company_source_is_accepted(self):
		self.policy(company_source="Employee")
		self.assertEqual(self.calculate().company, "Original Company")

	def test_company_source_cannot_be_changed_to_outlet(self):
		self.policy(company_source="Outlet")
		with self.assertRaises(frappe.ValidationError):
			self.calculate()

	def test_legacy_v1_snapshot_without_company_source_keeps_locked_company(self):
		self.assertNotIn("company_source", json.loads(self.entry.shift_policy_snapshot))
		self.assertEqual(self.calculate().company, "Original Company")

	def test_work_date_must_match_locked_shift_start_date(self):
		self.entry.shift_work_date = self.out.shift_work_date = "2026-10-14"
		self.policy(shift_work_date="2026-10-14")
		with self.assertRaises(frappe.ValidationError):
			self.calculate()

	def test_unknown_missing_out_policy_is_not_silently_applied(self):
		self.policy(missing_checkout_status="Absent")
		with self.assertRaises(frappe.ValidationError):
			service.calculate_session_attendance(self.entry, finalize_missing=True, now="2026-10-16 00:00:00")


class TestSessionPersistence(TestCase):
	def setUp(self):
		self.entry, self.out = session()
		self.policy = service._session_policy(self.entry)
		self.attendances, self.leaves = [], []
		self.read = self.mock("_read_session", side_effect=lambda *a, **k: (self.entry, self.out, self.policy))
		self.mock("_attendance_for_date", side_effect=lambda entry: deepcopy(self.attendances))
		self.leave_query = self.mock("_approved_leaves", side_effect=lambda entry: deepcopy(self.leaves))
		self.holiday = self.mock("_holiday_state", return_value=(False, False))
		self.mock("normalize_checkin_datetime", return_value=datetime(2026, 10, 16))
		self.db_write = self.mock("frappe.db.set_value")
		self.doc = MagicMock()
		self.doc.name = "ATT-CREATED"
		self.writer = self.mock("frappe.get_doc", return_value=self.doc)

	def run_session(self, **kwargs):
		return service._process_session(self.entry.name, self.out.name if self.out else None, **kwargs)

	def existing(self, **changes):
		row = frappe._dict(name="ATT-EXISTING", employee=self.entry.employee, attendance_date="2026-10-15", docstatus=1, status="Present", shift=None)
		row.update(changes)
		self.attendances = [row]
		return row

	def half_leave(self):
		self.leaves = [frappe._dict(name="LEAVE-1", half_day=1, half_day_date="2026-10-15", leave_type="Annual Leave")]
		return self.leaves[0]

	def test_creates_submitted_attendance_and_links_only_requested_pair(self):
		result = self.run_session()
		self.assertEqual(result["status"], "created")
		self.doc.insert.assert_called_once_with(ignore_permissions=True)
		self.doc.submit.assert_called_once()
		values = self.writer.call_args.args[0]
		self.assertEqual(values["source_checkin"], self.entry.name)
		self.assertEqual(values["source_checkout"], self.out.name)
		self.assertEqual([call.args[:2] for call in self.db_write.call_args_list], [("Employee Checkin", self.entry.name), ("Employee Checkin", self.out.name)])

	def test_replay_of_linked_pair_does_not_recreate_or_overwrite_attendance(self):
		row = self.existing()
		self.entry.attendance = self.out.attendance = row.name
		self.assertEqual(self.run_session()["status"], "already_processed")
		self.writer.assert_not_called()
		self.db_write.assert_not_called()

	def test_partial_link_is_repaired_without_recalculating(self):
		row = self.existing()
		self.entry.attendance = row.name
		self.assertEqual(self.run_session()["status"], "already_processed")
		self.db_write.assert_called_once_with("Employee Checkin", self.out.name, "attendance", row.name, update_modified=False)

	def test_different_attendance_links_fail_closed(self):
		self.existing()
		self.entry.attendance, self.out.attendance = "ATT-ONE", "ATT-TWO"
		with self.assertRaises(frappe.ValidationError):
			self.run_session()

	def test_cancelled_attendance_is_not_recreated(self):
		self.existing(docstatus=2)
		self.assertEqual(self.run_session()["reason"], "cancelled_attendance")
		self.writer.assert_not_called()

	def test_attendance_cancelled_with_its_leave_does_not_block_the_session(self):
		self.existing(docstatus=2, status="On Leave", leave_application="LEAVE-CANCELLED")
		self.assertEqual(self.run_session()["status"], "created")
		self.writer.assert_called()

	def test_draft_attendance_is_not_submitted_or_overwritten(self):
		self.existing(docstatus=0)
		with self.assertRaises(frappe.ValidationError):
			self.run_session()
		self.writer.assert_not_called()

	def test_multiple_active_attendances_fail_closed_even_for_different_shifts(self):
		self.existing()
		self.attendances.append(frappe._dict(name="SECOND", docstatus=1))
		with self.assertRaises(frappe.ValidationError):
			self.run_session()

	def test_attendance_with_other_source_pair_is_not_claimed(self):
		for changes in ({"source_checkin": "OTHER-IN"}, {"source_checkout": "OTHER-OUT"}):
			self.existing(**changes)
			with self.subTest(changes=changes), self.assertRaises(frappe.ValidationError):
				self.run_session()

	def test_attendance_request_and_full_day_leave_are_preserved_with_audit_comment(self):
		for changes in ({"attendance_request": "REQUEST-1"}, {"status": "On Leave", "leave_application": "LEAVE-1", "leave_type": "Annual Leave"}):
			self.existing(**changes)
			self.writer.reset_mock()
			self.db_write.reset_mock()
			with self.subTest(changes=changes):
				self.assertEqual(self.run_session()["status"], "preserved_existing")
				self.doc.add_comment.assert_called()
				self.assertTrue(all(call.args[0] == "Employee Checkin" for call in self.db_write.call_args_list))

	def test_modifiable_half_day_leave_merges_only_work_component(self):
		leave = self.half_leave()
		self.existing(status="Half Day", modify_half_day_status=1, leave_application=leave.name, leave_type=leave.leave_type)
		self.assertEqual(self.run_session()["status"], "updated_half_day")
		call = self.db_write.call_args_list[0]
		self.assertEqual(call.args[0], "Attendance")
		self.assertEqual(call.args[2]["status"], "Half Day")
		self.assertEqual(call.args[2]["half_day_status"], "Present")
		self.assertEqual(call.args[2]["leave_application"], leave.name)
		self.assertEqual(call.args[2]["modify_half_day_status"], 0)
		self.assertNotIn("company", call.args[2])
		self.doc.insert.assert_not_called()

	def test_finalized_half_day_and_requested_half_day_are_preserved(self):
		self.half_leave()
		self.existing(status="Half Day", modify_half_day_status=0, leave_application="LEAVE-1", leave_type="Annual Leave")
		self.assertEqual(self.run_session()["status"], "preserved_existing")
		self.existing(status="Half Day", modify_half_day_status=1, leave_application="LEAVE-1", leave_type="Annual Leave", attendance_request="REQUEST-1")
		self.assertEqual(self.run_session()["status"], "preserved_existing")

	def test_pending_half_day_leave_can_mark_working_half_absent(self):
		leave = self.half_leave()
		self.existing(status="Half Day", modify_half_day_status=1, leave_application=leave.name, leave_type=leave.leave_type)
		policy = json.loads(self.entry.shift_policy_snapshot)
		policy["working_hours_threshold_for_absent"] = 10
		self.entry.shift_policy_snapshot = self.out.shift_policy_snapshot = json.dumps(policy)
		self.assertEqual(self.run_session()["status"], "updated_half_day")
		self.assertEqual(self.db_write.call_args_list[0].args[2]["half_day_status"], "Absent")

	def test_new_attendance_respects_approved_full_day_leave(self):
		self.leaves = [frappe._dict(name="LEAVE-1", half_day=0, half_day_date=None, leave_type="Annual Leave")]
		self.run_session()
		values = self.writer.call_args.args[0]
		self.assertEqual(values["status"], "On Leave")
		self.assertEqual(values["leave_application"], "LEAVE-1")
		self.assertEqual(values["actual_overtime_duration"], 0)

	def test_multiple_approved_leaves_require_hr_review(self):
		self.half_leave()
		self.leaves.append(deepcopy(self.leaves[0]))
		with self.assertRaises(frappe.ValidationError):
			self.run_session()

	def test_outlet_holiday_does_not_skip_real_session_attendance(self):
		self.holiday.return_value = (True, False)
		self.assertEqual(self.run_session()["status"], "created")
		self.holiday.assert_not_called()

	def test_snapshot_allows_attendance_on_outlet_holiday(self):
		self.holiday.return_value = (True, False)
		self.policy["mark_auto_attendance_on_holidays"] = 1
		self.assertEqual(self.run_session()["status"], "created")

	def test_half_holiday_does_not_reduce_working_hour_thresholds(self):
		self.holiday.return_value = (False, True)
		with patch.object(service, "calculate_session_attendance", wraps=service.calculate_session_attendance) as calc:
			self.run_session()
		self.assertFalse(calc.call_args.kwargs.get("half_holiday", False))
		self.holiday.assert_not_called()

	def test_empty_or_deleted_holiday_list_never_blocks_real_session(self):
		for holiday_list in (None, "", "DELETED-LIST"):
			self.policy["holiday_list"] = holiday_list
			self.assertEqual(self.run_session()["status"], "created")
		self.holiday.assert_not_called()

	def test_authorized_skip_or_offshift_is_respected(self):
		for field in ("skip_auto_attendance", "offshift"):
			self.entry[field] = 1
			self.assertEqual(self.run_session()["status"], "skipped")
			self.entry[field] = 0
		self.writer.assert_not_called()

	def test_missing_out_has_no_out_link_or_fictitious_time(self):
		self.out = None
		self.run_session(finalize_missing=True)
		values = self.writer.call_args.args[0]
		self.assertIsNone(values["out_time"])
		self.assertEqual(values["working_hours"], 8)
		self.assertEqual(values["working_hours_source"], "Locked Shift Allocation")
		self.db_write.assert_called_once_with("Employee Checkin", self.entry.name, "attendance", "ATT-CREATED", update_modified=False)


class TestSessionReadsAndWorker(TestCase):
	def setUp(self):
		self.entry, self.out = session()

	def test_source_reads_lock_employee_then_current_in_then_only_paired_outs(self):
		events = []
		def read(dt, name, fields, **kwargs):
			events.append((dt, kwargs.get("for_update", False)))
			return self.entry if isinstance(fields, list) else self.entry.employee
		with patch("frappe.db.get_value", side_effect=read), patch("frappe.db.sql", return_value=[self.out]) as sql:
			service._read_session(self.entry.name, self.out.name, finalize_missing=False)
		self.assertEqual(events, [("Employee Checkin", False), ("Employee", True), ("Employee Checkin", True)])
		query = str(sql.call_args.args[0])
		self.assertIn("paired_checkin", query)
		self.assertIn("FOR UPDATE", query.upper())
		self.assertNotIn("last_sync", query)

	def test_multiple_or_different_outs_rejected_without_guess(self):
		for outs in ([], [frappe._dict(name="OTHER")], [self.out, deepcopy(self.out)]):
			with patch("frappe.db.get_value", side_effect=[self.entry.employee, self.entry.employee, self.entry]), patch("frappe.db.sql", return_value=outs):
				with self.subTest(outs=outs), self.assertRaises(frappe.ValidationError):
					service._read_session(self.entry.name, self.out.name, finalize_missing=False)

	def test_missing_finalization_refuses_existing_out(self):
		with patch("frappe.db.get_value", side_effect=[self.entry.employee, self.entry.employee, self.entry]), patch("frappe.db.sql", return_value=[self.out]):
			with self.assertRaises(frappe.ValidationError):
				service._read_session(self.entry.name, None, finalize_missing=True)

	def test_attendance_lookup_is_employee_work_date_scoped_current_read(self):
		with patch("frappe.db.sql", return_value=[]) as sql:
			service._attendance_for_date(self.entry)
		query = str(sql.call_args.args[0])
		self.assertIn("FOR UPDATE", query.upper())
		self.assertIn("employee", query)
		self.assertIn("attendance_date", query)

	def test_holiday_reader_never_uses_employee_holiday_assignment(self):
		with patch("frappe.db.exists", return_value=True), patch("frappe.get_all", return_value=[frappe._dict(is_half_day=1)]) as query:
			self.assertEqual(service._holiday_state(service._session_policy(self.entry), "2026-10-15"), (False, True))
		self.assertEqual(query.call_args.kwargs["filters"]["parent"], "Outlet Holidays")

	def test_missing_snapshot_holiday_list_fails_instead_of_employee_fallback(self):
		with patch("frappe.db.exists", return_value=False), self.assertRaises(frappe.ValidationError):
			service._holiday_state(service._session_policy(self.entry), "2026-10-15")

	def test_approved_leave_lookup_is_current_and_does_not_select_personal_holidays(self):
		with patch("frappe.db.sql", return_value=[]) as sql:
			service._approved_leaves(self.entry)
		query = str(sql.call_args.args[0])
		self.assertIn("FOR UPDATE", query.upper())
		self.assertIn("docstatus", query)
		self.assertIn("employee", query)
		self.assertNotIn("Holiday", query)

	def test_worker_does_not_commit_or_advance_global_sync_and_restores_user(self):
		user = frappe.session.user
		with patch.object(service, "_process_session", return_value={"status": "created"}) as process, patch("frappe.set_user") as set_user, patch("frappe.db.savepoint"), patch("frappe.db.commit") as commit, patch("frappe.db.set_value") as write:
			service.process_outlet_attendance(self.entry.name, self.out.name)
		process.assert_called_once_with(self.entry.name, self.out.name, finalize_missing=False)
		self.assertEqual([call.args[0] for call in set_user.call_args_list], ["Administrator", user])
		commit.assert_not_called()
		write.assert_not_called()

	def test_failure_rolls_back_session_and_logs_pair_reference_then_reraises(self):
		with patch.object(service, "_process_session", side_effect=RuntimeError("failure")), patch("frappe.set_user"), patch("frappe.db.savepoint"), patch("frappe.db.rollback") as rollback, patch("frappe.log_error") as log:
			with self.assertRaisesRegex(RuntimeError, "failure"):
				service.process_outlet_attendance(self.entry.name, self.out.name)
		rollback.assert_called_once_with(save_point="outlet_attendance_session")
		self.assertEqual(log.call_args.kwargs["reference_name"], self.entry.name)
		self.assertIn(self.out.name, log.call_args.kwargs["message"])
		self.assertTrue(log.call_args.kwargs["defer_insert"])

	def test_deadlock_invalidated_savepoint_does_not_hide_original_session_failure(self):
		with patch.object(service, "_process_session", side_effect=RuntimeError("original failure")), patch("frappe.set_user"), patch("frappe.db.savepoint"), patch("frappe.db.rollback", side_effect=RuntimeError("savepoint invalid")), patch("frappe.log_error") as log:
			with self.assertRaisesRegex(RuntimeError, "original failure"):
				service.process_outlet_attendance(self.entry.name, self.out.name)
		self.assertIn("Savepoint rollback failed", log.call_args.kwargs["message"])
