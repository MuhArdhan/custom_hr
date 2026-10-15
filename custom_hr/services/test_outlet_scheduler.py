# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""T09 guards, recovery, day-level absence and shared-native-shift tests."""

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.overrides.shift_type import CustomShiftType
from custom_hr.overrides.employee_checkin import process_shift_attendance_now
from custom_hr.services import outlet_scheduler as service

MODULE = "custom_hr.services.outlet_scheduler"


class TestCase(unittest.TestCase):
	def mock(self, name, **kwargs):
		p = patch(f"{MODULE}.{name}", **kwargs)
		self.addCleanup(p.stop)
		return p.start()

	def tearDown(self):
		frappe.clear_messages()


def stable_records():
	employee = frappe._dict(
		name="EMP", status="Active", outlet="Outlet", company="Company",
		modified="2026-10-14 12:00:00", creation="2026-01-01 12:00:00", date_of_joining="2026-01-01",
	)
	outlet = frappe._dict(
		name="Outlet", is_active=1, enable_outlet_auto_shift=1, company="Legacy Outlet Company", holiday_list="Outlet Holidays",
		modified="2026-10-14 12:00:00", outlet_auto_shift_effective_from="2026-10-15 00:00:00",
	)
	return employee, outlet


class TestDayContext(TestCase):
	def setUp(self):
		self.employee, self.outlet = stable_records()
		self.mock("configuration.OUTLET_AUTO_SHIFT_READY", new=True)
		self.now = self.mock("normalize_checkin_datetime", return_value=datetime(2026, 10, 16))
		self.query = self.mock("frappe.db.get_value", side_effect=lambda dt, *a, **k: self.employee if dt == "Employee" else self.outlet)
		self.resolution = {"mode": "Outlet", "message": "", "windows": [
			{"shift": "Shift1", "shift_work_date": "2026-10-15", "shift_end": "2026-10-15 13:00:00"},
			{"shift": "Shift2", "shift_work_date": "2026-10-15", "shift_end": "2026-10-15 18:00:00"},
		]}
		self.resolver = self.mock("resolve_outlet_shift", return_value=self.resolution)
		self.shift_versions = self.mock("frappe.db.sql", return_value=[frappe._dict(modified="2026-10-14 12:00:00")])

	def context(self):
		return service._day_context("EMP", "2026-10-15")

	def test_closed_day_is_eligible_without_assignments_or_selected_shift(self):
		context, reason = self.context()
		self.assertIsNone(reason)
		self.assertEqual(context.deadline, datetime(2026, 10, 15, 23, 59, 59))
		self.assertEqual(self.resolver.call_args.args, ("EMP", datetime(2026, 10, 15)))
		self.assertTrue(self.resolver.call_args.kwargs["for_update"])

	def test_employee_and_outlet_are_read_under_current_locks(self):
		self.context()
		self.assertEqual([call.args[0] for call in self.query.call_args_list], ["Employee", "Outlet"])
		self.assertTrue(all(call.kwargs["for_update"] for call in self.query.call_args_list))

	def test_exact_deadline_is_not_closed(self):
		self.now.return_value = datetime(2026, 10, 15, 23, 59, 59)
		self.assertEqual(self.context()[1], "day_still_open")

	def test_any_overnight_shift_extends_whole_day_deadline(self):
		self.resolution["windows"][1]["shift_end"] = "2026-10-16 06:00:00"
		self.assertEqual(self.context()[1], "day_still_open")
		self.now.return_value = datetime(2026, 10, 17)
		self.assertEqual(self.context()[0].deadline, datetime(2026, 10, 16, 23, 59, 59))

	def test_previous_work_date_windows_do_not_extend_this_day(self):
		self.resolution["windows"].append({"shift_work_date": "2026-10-14", "shift_end": "2026-10-18 06:00:00"})
		self.assertIsNotNone(self.context()[0])

	def test_partial_activation_day_is_excluded(self):
		self.outlet.outlet_auto_shift_effective_from = "2026-10-15 08:00:00"
		self.assertEqual(self.context()[1], "before_stable_activation_or_employment")

	def test_employee_change_cannot_backfill_historical_membership(self):
		self.employee.modified = "2026-10-15 10:00:00"
		self.assertEqual(self.context()[1], "before_stable_activation_or_employment")

	def test_outlet_configuration_change_cannot_backfill_historical_schedules(self):
		self.outlet.modified = "2026-10-15 10:00:00"
		self.assertEqual(self.context()[1], "before_stable_activation_or_employment")

	def test_shared_shift_master_change_cannot_backfill_historical_schedule(self):
		self.shift_versions.return_value = [frappe._dict(modified="2026-10-15 10:00:00")]
		self.assertEqual(self.context()[1], "before_stable_shift_configuration")

	def test_before_joining_or_after_relieving_is_excluded(self):
		self.employee.date_of_joining = "2026-10-16"
		self.assertIsNone(self.context()[0])
		self.employee.date_of_joining = "2026-01-01"
		self.employee.relieving_date = "2026-10-14"
		self.assertIsNone(self.context()[0])

	def test_disabled_mode_and_readiness_do_not_generate_absence(self):
		self.outlet.enable_outlet_auto_shift = 0
		self.assertEqual(self.context()[1], "mode_disabled")
		with patch(f"{MODULE}.configuration.OUTLET_AUTO_SHIFT_READY", False):
			self.assertEqual(self.context()[1], "not_active_or_ready")

	def test_invalid_company_or_unavailable_schedule_fails_closed(self):
		self.employee.company = None
		with self.assertRaises(frappe.ValidationError):
			self.context()
		self.employee.company = "Company"
		self.resolution["windows"] = []
		with self.assertRaises(frappe.ValidationError):
			self.context()


class TestNoLogDay(TestCase):
	def setUp(self):
		employee, outlet = stable_records()
		self.context = self.mock("_day_context", return_value=(frappe._dict(employee=employee, outlet=outlet, deadline=datetime(2026, 10, 15, 23, 59, 59)), None))
		self.logs = self.mock("_day_logs", return_value=[])
		self.attendance_query = self.mock("_attendance_for_date", return_value=[])
		self.leaves = self.mock("_approved_leaves", return_value=[])
		self.holiday = self.mock("_holiday_state", return_value=(False, False))
		self.doc = MagicMock()
		self.doc.name = "ATT"
		self.doc.insert.return_value = self.doc
		self.writer = self.mock("frappe.get_doc", return_value=self.doc)
		self.write = self.mock("frappe.db.set_value")

	def run_day(self):
		return service._process_day("EMP", "2026-10-15")

	def half_leave(self):
		leave = frappe._dict(name="LEAVE", half_day=1, half_day_date="2026-10-15", leave_type="Annual")
		self.leaves.return_value = [leave]
		return leave

	def existing(self, **changes):
		row = frappe._dict(name="ATT-OLD", docstatus=1, status="Present")
		row.update(changes)
		self.attendance_query.return_value = [row]
		return row

	def test_no_logs_creates_one_absent_without_shift_or_timestamps(self):
		self.assertEqual(self.run_day()["status"], "created")
		values = self.writer.call_args.args[0]
		self.assertEqual(values["status"], "Absent")
		self.assertEqual(values["company"], "Company")
		for field in ("shift", "in_time", "out_time", "source_checkin", "source_checkout", "working_hours_source"):
			self.assertIsNone(values[field])
		self.assertEqual(values["working_hours"], 0)
		self.assertEqual(values["missing_checkout"], 0)
		self.doc.submit.assert_called_once()

	def test_in_only_and_out_only_both_prevent_no_log_absence(self):
		for log_type in ("IN", "OUT"):
			self.logs.return_value = [frappe._dict(name="LOG", log_type=log_type)]
			self.assertEqual(self.run_day()["reason"], "logs_exist")
		self.writer.assert_not_called()

	def test_open_or_ineligible_day_does_not_inspect_logs_or_write(self):
		self.context.return_value = (None, "day_still_open")
		self.assertEqual(self.run_day()["reason"], "day_still_open")
		self.logs.assert_not_called()

	def test_existing_official_and_draft_are_not_overwritten(self):
		for changes in ({}, {"docstatus": 0}, {"status": "On Leave"}, {"attendance_request": "REQUEST"}):
			self.existing(**changes)
			self.assertEqual(self.run_day()["reason"], "official_attendance_exists")
		self.writer.assert_not_called()

	def test_cancelled_day_is_not_recreated(self):
		self.existing(docstatus=2)
		self.assertEqual(self.run_day()["reason"], "cancelled_attendance")
		self.writer.assert_not_called()

	def test_multiple_active_attendances_are_not_guessed(self):
		self.attendance_query.return_value = [frappe._dict(docstatus=1), frappe._dict(docstatus=1)]
		with self.assertRaises(frappe.ValidationError):
			self.run_day()

	def test_full_outlet_holiday_never_creates_absent(self):
		self.holiday.return_value = (True, False)
		self.assertEqual(self.run_day()["reason"], "outlet_holiday")
		self.writer.assert_not_called()

	def test_full_approved_leave_never_creates_absent(self):
		self.leaves.return_value = [frappe._dict(name="LEAVE", half_day=0)]
		self.assertEqual(self.run_day()["reason"], "approved_leave")
		self.writer.assert_not_called()

	def test_half_holiday_alone_still_has_a_working_half(self):
		self.holiday.return_value = (False, True)
		self.assertEqual(self.run_day()["status"], "created")
		self.assertEqual(self.writer.call_args.args[0]["status"], "Absent")

	def test_half_leave_without_attendance_creates_half_day_other_half_absent(self):
		self.half_leave()
		self.run_day()
		values = self.writer.call_args.args[0]
		self.assertEqual(values["status"], "Half Day")
		self.assertEqual(values["half_day_status"], "Absent")
		self.assertEqual(values["leave_application"], "LEAVE")

	def test_pending_half_leave_updates_only_other_half_and_source_metadata(self):
		self.half_leave()
		self.existing(status="Half Day", modify_half_day_status=1, leave_application="LEAVE", leave_type="Annual")
		self.assertEqual(self.run_day()["status"], "updated_half_day")
		values = self.write.call_args.args[2]
		self.assertEqual(values["half_day_status"], "Absent")
		self.assertNotIn("shift", values)
		self.assertNotIn("leave_application", values)
		self.doc.insert.assert_not_called()

	def test_half_day_holiday_and_half_leave_require_coverage_decision(self):
		self.half_leave()
		self.holiday.return_value = (False, True)
		self.assertEqual(self.run_day()["reason"], "half_day_coverage_requires_hr")
		self.writer.assert_not_called()

	def test_unverified_half_day_leave_is_not_finalized(self):
		self.existing(status="Half Day", modify_half_day_status=1, leave_application="UNKNOWN", leave_type="Annual")
		self.assertEqual(self.run_day()["reason"], "unverified_half_day_leave")

	def test_multiple_leaves_require_hr(self):
		leave = self.half_leave()
		self.leaves.return_value = [leave, leave]
		with self.assertRaises(frappe.ValidationError):
			self.run_day()


class TestRecoveryAndDispatch(TestCase):
	def setUp(self):
		self.entry = frappe._dict(name="IN", employee="EMP", checkout_deadline="2026-10-15 23:59:59")
		self.out = self.mock("_linked_checkout", return_value=None)
		self.now = self.mock("normalize_checkin_datetime", return_value=datetime(2026, 10, 16))
		self.enqueue = self.mock("frappe.enqueue")
		self.mock("_settled_dates", return_value=set())

	def test_missing_out_is_queued_only_after_deadline(self):
		self.assertTrue(service._enqueue_session(self.entry))
		values = self.enqueue.call_args.kwargs
		self.assertTrue(values["finalize_missing"])
		self.assertIsNone(values["source_checkout"])
		self.assertTrue(values["enqueue_after_commit"])
		self.assertTrue(values["deduplicate"])

	def test_open_and_exact_deadline_missing_out_are_not_queued(self):
		for stamp in (datetime(2026, 10, 15, 13), datetime(2026, 10, 15, 23, 59, 59)):
			self.now.return_value = stamp
			self.assertFalse(service._enqueue_session(self.entry))
		self.enqueue.assert_not_called()

	def test_complete_pair_queues_before_deadline_without_mode_lookup(self):
		self.out.return_value = frappe._dict(name="OUT")
		self.now.return_value = datetime(2026, 10, 15, 13)
		self.assertTrue(service._enqueue_session(self.entry))
		self.assertEqual(self.enqueue.call_args.kwargs["source_checkout"], "OUT")
		self.assertFalse(self.enqueue.call_args.kwargs["finalize_missing"])

	def test_job_identity_is_stable_for_same_session_and_changes_for_out(self):
		service._enqueue_session(self.entry)
		missing_id = self.enqueue.call_args.kwargs["job_id"]
		service._enqueue_session(self.entry)
		self.assertEqual(missing_id, self.enqueue.call_args.kwargs["job_id"])
		self.out.return_value = frappe._dict(name="OUT")
		service._enqueue_session(self.entry)
		self.assertNotEqual(missing_id, self.enqueue.call_args.kwargs["job_id"])

	def test_recovery_query_is_keyset_paged_and_not_gated_by_current_outlet_mode(self):
		with patch("frappe.db.sql", side_effect=[[self.entry], []]) as sql:
			self.assertEqual(service.recover_outlet_sessions(), 1)
		self.assertEqual(sql.call_count, 2)
		query = str(sql.call_args.args[0])
		self.assertIn("paired_checkin", query)
		self.assertIn("attendance_source", query)
		self.assertNotIn("tabOutlet", query)
		self.assertIn("ORDER BY", query.upper())
		self.assertNotIn("OFFSET", query.upper())

	def test_malformed_session_does_not_starve_valid_recovery(self):
		broken = frappe._dict(name="BROKEN", employee="EMP", checkout_deadline=None)
		with patch("frappe.db.sql", side_effect=[[broken, self.entry], []]), patch("frappe.log_error") as log:
			self.assertEqual(service.recover_outlet_sessions(), 1)
		self.assertEqual(log.call_args.kwargs["reference_name"], "BROKEN")

	def test_readiness_off_still_runs_recovery_but_no_absence_dispatch(self):
		with patch(f"{MODULE}.configuration.OUTLET_AUTO_SHIFT_READY", False), patch.object(service, "recover_outlet_sessions", return_value=3), patch("frappe.get_all") as query:
			self.assertEqual(service.run_outlet_attendance_scheduler(), 3)
		query.assert_not_called()

	def test_ready_dispatches_active_outlet_employees_without_assignment_lookup(self):
		with patch(f"{MODULE}.configuration.OUTLET_AUTO_SHIFT_READY", True), patch.object(service, "recover_outlet_sessions", return_value=0), patch("frappe.get_all", side_effect=[["Outlet"], ["EMP"]]) as query:
			self.assertEqual(service.run_outlet_attendance_scheduler(), 1)
		self.assertEqual([call.args[0] for call in query.call_args_list], ["Outlet", "Employee"])
		self.assertEqual(self.enqueue.call_args.kwargs["employee"], "EMP")

	def test_finalize_employee_range_respects_stable_start_and_excludes_today(self):
		employee, outlet = stable_records()
		self.now.return_value = datetime(2026, 10, 17)
		with patch(f"{MODULE}.configuration.OUTLET_AUTO_SHIFT_READY", True), patch("frappe.db.get_value", side_effect=[employee, outlet]), patch.object(service, "process_outlet_day") as process:
			service.finalize_outlet_days("EMP")
		self.assertEqual([str(call.args[1]) for call in process.call_args_list], ["2026-10-15", "2026-10-16"])

	def test_day_failure_does_not_starve_later_dates(self):
		employee, outlet = stable_records()
		self.now.return_value = datetime(2026, 10, 17)
		with patch(f"{MODULE}.configuration.OUTLET_AUTO_SHIFT_READY", True), patch("frappe.db.get_value", side_effect=[employee, outlet]), patch.object(service, "process_outlet_day", side_effect=[frappe.ValidationError("bad date"), None]) as process:
			service.finalize_outlet_days("EMP")
		self.assertEqual(process.call_count, 2)

	def test_already_settled_dates_are_not_reprocessed_hourly(self):
		employee, outlet = stable_records()
		self.now.return_value = datetime(2026, 10, 17)
		with patch(f"{MODULE}.configuration.OUTLET_AUTO_SHIFT_READY", True), patch("frappe.db.get_value", side_effect=[employee, outlet]), patch.object(service, "_settled_dates", return_value={datetime(2026, 10, 15).date()}), patch.object(service, "process_outlet_day") as process:
			service.finalize_outlet_days("EMP")
		self.assertEqual([str(call.args[1]) for call in process.call_args_list], ["2026-10-16"])

	def test_day_log_query_uses_locked_work_date_and_falls_back_only_when_unknown(self):
		with patch("frappe.db.sql", return_value=[]) as sql:
			service._day_logs("EMP", "2026-10-15")
		query = str(sql.call_args.args[0]).upper()
		self.assertIn("FOR UPDATE", query)
		self.assertIn("IS NULL", query)
		self.assertIn("SHIFT_WORK_DATE", query)

	def test_day_worker_rolls_back_and_logs_employee_date_without_commit(self):
		with patch.object(service, "_process_day", side_effect=RuntimeError("failure")), patch("frappe.set_user"), patch("frappe.db.savepoint"), patch("frappe.db.rollback") as rollback, patch("frappe.db.commit") as commit, patch("frappe.log_error") as log:
			with self.assertRaises(RuntimeError):
				service.process_outlet_day("EMP", "2026-10-15")
		rollback.assert_called_once_with(save_point="outlet_absence_day")
		commit.assert_not_called()
		self.assertEqual(log.call_args.kwargs["reference_name"], "EMP")
		self.assertIn("2026-10-15", log.call_args.kwargs["message"])


class TestNativeIsolation(TestCase):
	def setUp(self):
		self.shift = CustomShiftType({"doctype": "Shift Type", "name": "Shared Shift", "start_time": "05:00:00", "last_sync_of_checkin": "2026-10-17 00:00:00"})
		self.day_logs = self.mock("_day_logs", return_value=[])

	def test_shared_shift_filters_only_persisted_outlet_logs_including_plain_dicts(self):
		logs = [{"name": "NATIVE"}, {"name": "OUTLET"}]
		with patch("frappe.get_all", return_value=["OUTLET"]):
			self.assertEqual(self.shift._native_logs(logs), [logs[0]])

	def test_empty_native_log_list_does_not_query_database(self):
		with patch("frappe.get_all") as query:
			self.assertEqual(self.shift._native_logs([]), [])
		query.assert_not_called()

	def test_native_get_checkins_and_queued_process_both_filter_sources(self):
		logs = [frappe._dict(name="NATIVE"), frappe._dict(name="OUTLET")]
		with patch("hrms.hr.doctype.shift_type.shift_type.ShiftType.get_employee_checkins", return_value=logs), patch("frappe.get_all", return_value=["OUTLET"]), patch("hrms.hr.doctype.shift_type.shift_type.ShiftType._process") as process:
			self.assertEqual(self.shift.get_employee_checkins(), [logs[0]])
			self.shift._process(logs)
		process.assert_called_once_with([logs[0]])

	def test_native_absence_dates_exclude_outlet_but_keep_preactivation(self):
		with patch("hrms.hr.doctype.shift_type.shift_type.ShiftType.get_dates_for_attendance", return_value=["2026-10-14", "2026-10-15"]), patch("custom_hr.overrides.shift_type.native_absence_is_managed", side_effect=lambda e, d: d == "2026-10-15"):
			self.assertEqual(self.shift.get_dates_for_attendance("EMP"), ["2026-10-14"])

	def test_native_absence_helper_uses_current_reads_and_retained_effective_boundary(self):
		settings = frappe._dict(outlet_auto_shift_effective_from="2026-10-15 08:00:00", enable_outlet_auto_shift=0, modified="2026-10-15 12:00:00")
		with patch("frappe.db.get_value", side_effect=["Outlet", None, None, settings]) as query:
			self.assertTrue(service.native_absence_is_managed("EMP", "2026-10-15"))
		self.assertTrue(all(call.kwargs["for_update"] for call in query.call_args_list))

	def test_persisted_session_or_cancelled_outlet_attendance_still_owns_day(self):
		for reads in ([None, "OUTLET-IN"], [None, None, "CANCELLED-ATT"]):
			with patch("frappe.db.get_value", side_effect=reads):
				self.assertTrue(service.native_absence_is_managed("EMP", "2026-10-15"))

	def test_native_date_before_effective_or_without_outlet_stays_native(self):
		settings = frappe._dict(outlet_auto_shift_effective_from="2026-10-15", enable_outlet_auto_shift=1)
		with patch("frappe.db.get_value", side_effect=["Outlet", None, None, settings]):
			self.assertFalse(service.native_absence_is_managed("EMP", "2026-10-14"))
		with patch("frappe.db.get_value", side_effect=[None, None, None]):
			self.assertFalse(service.native_absence_is_managed("EMP", "2026-10-15"))

	def test_orphan_outlet_out_without_work_date_also_blocks_native_absence(self):
		self.day_logs.return_value = [frappe._dict(name="ORPHAN-OUT", attendance_source="Outlet", log_type="OUT")]
		with patch("frappe.db.get_value", side_effect=[None, None]):
			self.assertTrue(service.native_absence_is_managed("EMP", "2026-10-15"))

	def test_future_native_absence_resumes_after_mode_off_boundary(self):
		settings = frappe._dict(outlet_auto_shift_effective_from="2026-10-15", enable_outlet_auto_shift=0, modified="2026-10-16 10:00:00")
		with patch("frappe.db.get_value", side_effect=["Outlet", None, None, settings]):
			self.assertFalse(service.native_absence_is_managed("EMP", "2026-10-17"))

	def test_native_half_day_absence_does_not_finalize_outlet_leave(self):
		rows = [frappe._dict(name="OUTLET-LEAVE", attendance_date="2026-10-15")]
		with patch("frappe.get_all", return_value=rows), patch("custom_hr.overrides.shift_type.native_absence_is_managed", return_value=True), patch("custom_hr.overrides.shift_type.get_employee_shift") as resolve, patch("frappe.db.set_value") as write:
			self.shift.mark_absent_for_half_day_dates("EMP")
		resolve.assert_not_called()
		write.assert_not_called()

	def test_native_half_day_absence_algorithm_still_runs_for_unmanaged_date(self):
		rows = [frappe._dict(name="NATIVE-LEAVE", attendance_date="2026-10-14")]
		details = frappe._dict(shift_type=frappe._dict(name=self.shift.name), actual_end=datetime(2026, 10, 14, 13))
		with patch("frappe.get_all", return_value=rows), patch("custom_hr.overrides.shift_type.native_absence_is_managed", return_value=False), patch("custom_hr.overrides.shift_type.get_employee_shift", return_value=details), patch("frappe.db.set_value") as write, patch("frappe.get_doc"):
			self.shift.mark_absent_for_half_day_dates("EMP")
		self.assertEqual(write.call_args.args[1], "NATIVE-LEAVE")

	def test_native_realtime_job_with_only_outlet_logs_cannot_advance_sync(self):
		with patch("frappe.db.sql", return_value=[]) as sql, patch("frappe.db.set_value") as write, patch("frappe.get_doc") as doc:
			process_shift_attendance_now("Shared Shift", "EMP")
		write.assert_not_called()
		doc.assert_not_called()
		self.assertIn("attendance_source", str(sql.call_args.args[0]))

	def test_settled_discovery_keeps_pending_half_leave_but_skips_cancelled_and_official_dates(self):
		rows = [
			frappe._dict(attendance_date="2026-10-15", docstatus=2, status="Present"),
			frappe._dict(attendance_date="2026-10-16", docstatus=1, status="Half Day", modify_half_day_status=1),
			frappe._dict(attendance_date="2026-10-17", docstatus=1, status="Present"),
		]
		with patch("frappe.get_all", return_value=rows):
			result = service._settled_dates("EMP", "2026-10-15", "2026-10-17")
		self.assertEqual({str(day) for day in result}, {"2026-10-15", "2026-10-17"})
