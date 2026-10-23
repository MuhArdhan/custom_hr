# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""T11 self-service request reconciliation and session-bound OUT preconditions."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.api import checkin
from custom_hr.services import checkin_submission as submission

REQUEST_ID = "d288162e-b86c-443d-801d-5ccf98d92d84"


class TestCase(unittest.TestCase):
	def mock(self, target, **kwargs):
		p = patch(target, **kwargs)
		self.addCleanup(p.stop)
		return p.start()

	def tearDown(self):
		frappe.clear_messages()


class TestRequestResult(TestCase):
	def setUp(self):
		self.employee = frappe._dict(name="EMP", user_id=frappe.session.user, status="Active")
		self.mock("custom_hr.api.checkin.get_current_employee", return_value="EMP")
		self.mock("custom_hr.api.checkin._employee_record", return_value=self.employee)
		self.read = self.mock("frappe.db.get_value", return_value=None)

	def test_uncommitted_or_missing_request_returns_none_without_write(self):
		with patch("frappe.db.set_value") as write, patch("frappe.db.commit") as commit:
			self.assertIsNone(checkin.get_checkin_request_result(REQUEST_ID))
		write.assert_not_called()
		commit.assert_not_called()

	def test_result_is_employee_scoped_and_uses_only_persisted_response_fields(self):
		self.read.return_value = frappe._dict(name="SAVED", employee="EMP", log_type="IN", shift="Actually Saved", time="2026-10-15 09:30:00")
		result = checkin.get_checkin_request_result(REQUEST_ID)
		self.assertEqual(result["shift"], "Actually Saved")
		self.assertTrue(result["replayed"])
		self.assertEqual(self.read.call_args.args[1], submission.request_log_name("EMP", REQUEST_ID))
		self.assertNotIn("shift_policy_snapshot", result)
		self.assertFalse(self.read.call_args.kwargs.get("for_update", False))

	def test_empty_or_invalid_uuid_does_not_read_arbitrary_logs(self):
		for value in (None, "", "not-a-uuid"):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				checkin.get_checkin_request_result(value)
		self.read.assert_not_called()

	def test_inactive_or_foreign_employee_account_is_rejected_even_for_hr(self):
		for field, value in (("status", "Left"), ("user_id", "foreign@example.com")):
			old = self.employee[field]
			self.employee[field] = value
			with self.subTest(field=field), self.assertRaises(frappe.PermissionError):
				checkin.get_checkin_request_result(REQUEST_ID)
			self.employee[field] = old
		self.read.assert_not_called()

	def test_mismatched_record_owner_cannot_be_exposed(self):
		self.read.return_value = frappe._dict(name="FOREIGN", employee="OTHER")
		with self.assertRaises(frappe.PermissionError):
			checkin.get_checkin_request_result(REQUEST_ID)

	def test_lookup_does_not_accept_client_employee_or_time(self):
		with self.assertRaises(TypeError):
			checkin.get_checkin_request_result(REQUEST_ID, employee="OTHER", time="2026-10-15")


class TestExpectedCheckout(TestCase):
	def setUp(self):
		self.mock("custom_hr.services.checkin_submission._employee_record", return_value=frappe._dict(user_id=frappe.session.user, status="Active"))
		self.latest = self.mock("custom_hr.services.checkin_submission._latest_in_for_checkout", return_value=frappe._dict(name="CURRENT-IN"))
		self.read = self.mock("frappe.db.get_value", return_value=None)
		self.doc = MagicMock(name="doc")
		self.doc.name = "NEW-OUT"
		self.writer = self.mock("frappe.get_doc", return_value=self.doc)

	def test_matching_expected_in_is_a_precondition_not_a_pair_override(self):
		submission.submit_self_checkin("EMP", "OUT", expected_checkin="CURRENT-IN")
		self.latest.assert_called_once_with("EMP")
		self.doc.insert.assert_called_once()
		self.assertNotIn("paired_checkin", self.writer.call_args.args[0])

	def test_retry_of_old_out_cannot_close_a_newer_session(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Sesi IN sudah berubah"):
			submission.submit_self_checkin("EMP", "OUT", expected_checkin="OLD-IN", request_id=REQUEST_ID)
		self.writer.assert_not_called()

	def test_no_current_in_or_empty_precondition_fails_before_insert(self):
		for value in ("", "OLD-IN"):
			self.latest.return_value = None
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				submission.submit_self_checkin("EMP", "OUT", expected_checkin=value)
		self.writer.assert_not_called()

	def test_committed_out_replay_is_returned_even_when_current_session_changed(self):
		self.read.return_value = frappe._dict(name="COMMITTED-OUT", employee="EMP", log_type="OUT")
		row, replayed = submission.submit_self_checkin("EMP", "OUT", expected_checkin="OLD-IN", request_id=REQUEST_ID)
		self.assertTrue(replayed)
		self.assertEqual(row.name, "COMMITTED-OUT")
		self.latest.assert_not_called()
		self.writer.assert_not_called()

	def test_legacy_call_without_precondition_preserves_supported_api_contract(self):
		submission.submit_self_checkin("EMP", "OUT")
		self.doc.insert.assert_called_once()
		self.latest.assert_not_called()

	def test_in_does_not_accept_an_out_pair_precondition(self):
		with self.assertRaises(frappe.ValidationError):
			submission.submit_self_checkin("EMP", "IN", expected_checkin="CURRENT-IN")
		self.writer.assert_not_called()

	def test_standard_endpoint_forwards_the_precondition(self):
		with patch.object(checkin, "get_current_employee", return_value="EMP"), patch.object(checkin, "submit_self_checkin", return_value=(frappe._dict(employee="EMP", log_type="OUT"), False)) as writer:
			checkin.submit_checkin("OUT", expected_checkin="CURRENT-IN")
		self.assertEqual(writer.call_args.kwargs["expected_checkin"], "CURRENT-IN")
