import unittest
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.api import payroll_attendance as payroll
from custom_hr.hrm.doctype.hrm_attendance_payroll_settings.hrm_attendance_payroll_settings import (
	HRMAttendancePayrollSettings,
)


class TestPayrollAttendance(unittest.TestCase):
	def setUp(self):
		# Native precision rounding consults System Settings. Unit tests have no site.
		rounding = patch("frappe.utils.data.rounded", side_effect=lambda value, precision, method=None: round(value, precision))
		rounding.start()
		self.addCleanup(rounding.stop)

	def attendance(self, **values):
		return frappe._dict(name="ATT-1", status="Present", shift="Shift A", attendance_date="2026-10-13",
			in_time=None, out_time=None, half_day_status=None, **values)

	def shift(self, **values):
		return frappe._dict(start_time="08:00:00", end_time="16:00:00",
			begin_check_in_before_shift_start_time=60, allow_check_out_after_shift_end_time=180, **values)

	def rule(self, **values):
		data = {"category": "Alpha", "company": "Test Company", "salary_component": "Alpha", "enabled": 0,
			"method": "Rekap Saja", "rate": 0, "divisor": 0, "multiplier": 1,
			"from_date": "2026-10-01", "to_date": None}
		data.update(values)
		return frappe._dict(data)

	def classify(self, attendance=None, logs=(), shift=None, **options):
		return payroll.classify_day("2026-10-13", attendance, logs, shift, **options)

	def test_missing_attendance_is_not_alpha(self):
		event, issues = self.classify()
		self.assertIsNone(event)
		self.assertTrue(issues)

	def test_explicit_absent_has_priority_over_missing_punches(self):
		doc = self.attendance()
		doc.status = "Absent"
		event, issues = self.classify(doc, shift=self.shift())
		self.assertEqual(event, {"category": "Alpha", "quantity": 1.0})
		self.assertFalse(issues)

	def test_half_day_absence(self):
		doc = self.attendance()
		doc.update(status="Half Day", half_day_status="Absent")
		event, _ = self.classify(doc)
		self.assertEqual(event["quantity"], 0.5)

	def test_paid_leave_does_not_generate_penalties(self):
		event, issues = self.classify(self.attendance(), has_leave=True)
		self.assertIsNone(event)
		self.assertFalse(issues)

	def test_unpaid_half_day_leave_is_not_converted_to_hours(self):
		event, _ = self.classify(has_leave=True, leave_quantity=0.5)
		self.assertEqual(event, {"category": "Izin", "quantity": 0.5})

	def test_wfh_is_not_missing_outlet_checkin(self):
		doc = self.attendance()
		doc.status = "Work From Home"
		event, issues = self.classify(doc)
		self.assertIsNone(event)
		self.assertFalse(issues)

	def test_missing_both_punches_requires_verification(self):
		event, issues = self.classify(self.attendance(), shift=self.shift())
		self.assertIsNone(event)
		self.assertTrue(issues)

	def test_missing_out_has_priority_over_lateness(self):
		doc = self.attendance()
		doc.in_time = "2026-10-13 09:00:00"
		event, _ = self.classify(doc, shift=self.shift())
		self.assertEqual(event["category"], "Tidak Absen OUT")

	def test_missing_in(self):
		doc = self.attendance()
		doc.out_time = "2026-10-13 16:00:00"
		event, _ = self.classify(doc, shift=self.shift())
		self.assertEqual(event["category"], "Tidak Absen IN")

	def test_tolerance_boundary(self):
		doc = self.attendance()
		doc.update(in_time="2026-10-13 08:05:00", out_time="2026-10-13 16:00:00")
		event, _ = self.classify(doc, shift=self.shift(), tolerance=5)
		self.assertIsNone(event)
		doc.in_time = "2026-10-13 08:06:00"
		event, _ = self.classify(doc, shift=self.shift(), tolerance=5)
		self.assertEqual(event["category"], "Terlambat")
		self.assertEqual(event["minutes"], 6)

	def test_cross_midnight_shift(self):
		shift = self.shift()
		shift.update(start_time="22:00:00", end_time="06:00:00")
		logs = [frappe._dict(name="IN", time="2026-10-13 21:55:00", log_type="IN", attendance=None, shift="Shift A"),
			frappe._dict(name="OUT", time="2026-10-14 06:10:00", log_type="OUT", attendance=None, shift="Shift A")]
		event, issues = self.classify(self.attendance(), logs=logs, shift=shift)
		self.assertIsNone(event)
		self.assertFalse(issues)

	def test_logs_linked_to_other_attendance_are_not_reused(self):
		logs = [frappe._dict(time="2026-10-13 08:00:00", log_type="IN", attendance="OTHER", shift="Shift A")]
		event, issues = self.classify(self.attendance(), logs=logs, shift=self.shift())
		self.assertIsNone(event)
		self.assertTrue(issues)

	def test_invalid_time_order_requires_verification(self):
		doc = self.attendance()
		doc.update(in_time="2026-10-13 09:00:00", out_time="2026-10-13 08:00:00")
		event, issues = self.classify(doc, shift=self.shift())
		self.assertIsNone(event)
		self.assertTrue(issues)

	def test_disabled_rule_estimates_zero(self):
		self.assertEqual(payroll.estimate_amount(2, self.rule(rate=10000), 3000000), 0)

	def test_fixed_rate_and_base_divisor(self):
		self.assertEqual(payroll.estimate_amount(2, self.rule(enabled=1, method="Tarif Tetap", rate=10000), None), 20000)
		self.assertEqual(payroll.estimate_amount(0.5,
			self.rule(enabled=1, method="Base / Pembagi", divisor=30), 3000000), 50000)

	def test_native_lwp_prevents_double_deduction(self):
		self.assertEqual(payroll.estimate_amount(2,
			self.rule(enabled=1, method="Tarif Tetap", rate=10000), 3000000, native_handled=True), 0)

	def test_missing_base_does_not_guess_amount(self):
		self.assertEqual(payroll.estimate_amount(1,
			self.rule(enabled=1, method="Base / Pembagi", divisor=30), None), 0)

	def test_effective_rules(self):
		rules = [self.rule(to_date="2026-10-15"), self.rule(from_date="2026-10-16", rate=20000)]
		self.assertEqual(payroll.applicable_rule(rules, "Alpha", "2026-10-16").rate, 20000)
		self.assertIsNone(payroll.applicable_rule(rules, "Alpha", "2026-09-30"))

	def test_overlapping_rules_rejected(self):
		with patch.object(frappe, "throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				payroll.applicable_rule([self.rule(), self.rule()], "Alpha", "2026-10-13")

	def test_settings_validate_deduction_component(self):
		settings = frappe._dict(company="Test Company", from_date="2026-10-01", disabled=1,
			late_tolerance_minutes=0, rules=[self.rule()])
		with patch.object(frappe, "db", MagicMock()) as db:
			db.get_value.return_value = "Earning"
			with patch.object(frappe, "throw", side_effect=ValueError):
				with self.assertRaises(ValueError):
					HRMAttendancePayrollSettings.validate(settings)

	def test_settings_require_positive_divisor_for_enabled_base_rule(self):
		settings = frappe._dict(company="Test Company", from_date="2026-10-01", disabled=1, late_tolerance_minutes=0,
			rules=[self.rule(enabled=1, method="Base / Pembagi", divisor=0)])
		with patch.object(frappe, "db", MagicMock()) as db:
			db.get_value.return_value = "Deduction"
			with patch.object(frappe, "throw", side_effect=ValueError):
				with self.assertRaises(ValueError):
					HRMAttendancePayrollSettings.validate(settings)

	def test_preview_checks_hr_role(self):
		with patch.object(frappe, "only_for", side_effect=PermissionError):
			with self.assertRaises(PermissionError):
				payroll.preview_attendance("EMP", "2026-10-01", "2026-10-31")

	def test_submitted_slip_cannot_refresh_snapshot(self):
		doc = MagicMock(docstatus=1)
		with patch.object(frappe, "only_for"):
			with patch.object(frappe, "get_doc", return_value=doc):
				with patch.object(frappe, "throw", side_effect=ValueError):
					with self.assertRaises(ValueError):
						payroll.save_attendance_snapshot("SLIP")

	def test_legacy_slips_without_snapshot_unaffected(self):
		with patch.object(payroll, "collect_summary") as collect:
			payroll.validate_snapshot(frappe._dict())
			collect.assert_not_called()

	def test_stale_snapshot_blocks_submit(self):
		doc = frappe._dict(employee="EMP", start_date="2026-10-01", end_date="2026-10-31",
			custom_hr_attendance_hash="old", custom_hr_attendance_snapshot="[]")
		with patch.object(payroll, "collect_summary", return_value={"source_hash": "new", "rows": [], "blockers": []}):
			with patch.object(frappe, "throw", side_effect=ValueError):
				with self.assertRaises(ValueError):
					payroll.validate_snapshot(doc)

	def test_incomplete_snapshot_blocks_submit(self):
		doc = frappe._dict(employee="EMP", start_date="2026-10-01", end_date="2026-10-31",
			custom_hr_attendance_hash="hash", custom_hr_attendance_snapshot="[]")
		with patch.object(payroll, "collect_summary", return_value={"blockers": ["Missing Attendance"]}):
			with patch.object(frappe, "throw", side_effect=ValueError):
				with self.assertRaises(ValueError):
					payroll.validate_snapshot(doc)

	def test_snapshot_payload_hash_is_stable_and_sensitive(self):
		self.assertEqual(payroll.fingerprint({"a": 1, "b": 2}), payroll.fingerprint({"b": 2, "a": 1}))
		self.assertNotEqual(payroll.fingerprint({"rate": 10}), payroll.fingerprint({"rate": 20}))

	def test_rules_are_scoped_to_company_and_specific_rule_overrides_common(self):
		common = self.rule(company=None)
		specific = self.rule(company="Test Company", rate=20000)
		other = self.rule(company="Other Company", rate=50000)
		self.assertEqual(payroll.applicable_rule([common, specific, other], "Alpha", "2026-10-13", "Test Company").rate, 20000)
		self.assertEqual(payroll.applicable_rule([common, specific, other], "Alpha", "2026-10-13", "Third Company"), common)

	def test_company_policy_overlap_is_rejected(self):
		settings = frappe._dict(doctype=payroll.SETTINGS, name="NEW", company="Test Company",
			from_date="2026-10-01", to_date=None, disabled=0, late_tolerance_minutes=0, rules=[])
		with patch.object(frappe, "get_all", return_value=[frappe._dict(
			name="EXISTING", from_date="2026-10-14", to_date=None)]) as query:
			with patch.object(frappe, "throw", side_effect=ValueError):
				with self.assertRaises(ValueError):
					HRMAttendancePayrollSettings.validate(settings)
			self.assertEqual(query.call_args.kwargs["filters"]["company"], "Test Company")

	def test_non_overlapping_company_policy_is_allowed(self):
		settings = frappe._dict(doctype=payroll.SETTINGS, name="NEW", company="Test Company",
			from_date="2026-11-01", to_date=None, disabled=0, late_tolerance_minutes=0, rules=[])
		with patch.object(frappe, "get_all", return_value=[frappe._dict(
			name="EXISTING", from_date="2026-10-01", to_date="2026-10-31")]):
			HRMAttendancePayrollSettings.validate(settings)

	def test_lateness_in_hours_uses_measured_minutes(self):
		quantity, unit = payroll.event_quantity(
			{"category": "Terlambat", "quantity": 1, "minutes": 90}, self.rule(unit="Jam"))
		self.assertEqual((quantity, unit), (1.5, "Jam"))
		self.assertEqual(payroll.estimate_amount(quantity,
			self.rule(unit="Jam", enabled=1, method="Tarif Tetap", rate=20000), None), 30000)

	def test_half_day_hours_use_explicit_hr_conversion(self):
		self.assertEqual(payroll.event_quantity({"category": "Izin", "quantity": 0.5},
			self.rule(unit="Jam", hours_per_day=8)), (4, "Jam"))

	def test_hours_cannot_be_guessed_without_conversion(self):
		with patch.object(frappe, "throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				payroll.event_quantity({"category": "Alpha", "quantity": 1}, self.rule(unit="Jam"))

	def test_missing_punch_cannot_be_converted_to_hours(self):
		with patch.object(frappe, "throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				payroll.event_quantity({"category": "Tidak Absen OUT", "quantity": 1},
					self.rule(unit="Jam", hours_per_day=8))

	def test_json_snapshot_roundtrip(self):
		import json

		rows = [{"category": "Terlambat", "quantity": 1.5, "unit": "Jam"}]
		self.assertEqual(payroll.snapshot_rows(frappe._dict(
			custom_hr_attendance_snapshot=json.dumps(rows))), rows)

	def test_invalid_snapshot_is_rejected(self):
		with patch.object(frappe, "throw", side_effect=ValueError):
			for value in ("broken", "{}", '["wrong"]'):
				with self.assertRaises(ValueError):
					payroll.snapshot_rows(frappe._dict(custom_hr_attendance_snapshot=value))
