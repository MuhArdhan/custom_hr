import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import frappe
from jinja2 import Environment, FileSystemLoader

from custom_hr import contract_notifications as notifications


class TestContractNotifications(unittest.TestCase):
	def setUp(self):
		# Render actual templates without requiring a site/database in unit tests.
		environment = Environment(loader=FileSystemLoader(Path(notifications.__file__).parent))
		renderer = patch.object(frappe, "render_template",
			side_effect=lambda path, context: environment.get_template(path).render(context))
		renderer.start()
		self.addCleanup(renderer.stop)

	def settings(self, **overrides):
		return frappe._dict({
			"enabled": 1, "dry_run": 1, "test_mode": 1,
			"reminder_days": "30,14,7,3",
			"hr_recipients": "upalmrobot@gmail.com",
			"allowed_recipients": "upalmrobot@gmail.com\nhetiayasiwa@gmail.com",
			**overrides,
		})

	def employee(self, **overrides):
		return frappe._dict({
			"name": "HR-EMP-00007", "employee_name": "Employee Test",
			"contract_end_date": "2026-10-16", "company": "Test Company", "department": None,
			"user_id": None, "company_email": None, "personal_email": "hetiayasiwa@gmail.com",
			"prefered_contact_email": None, "prefered_email": None, **overrides,
		})

	def test_days_are_unique_sorted(self):
		self.assertEqual(notifications.parse_reminder_days("7,3,7,30"), [3, 7, 30])

	def test_invalid_days(self):
		with patch.object(frappe, "throw", side_effect=ValueError):
			for value in ["", "3,no", "-1"]:
				with self.subTest(value=value), self.assertRaises(ValueError):
					notifications.parse_reminder_days(value)

	def test_email_validation_and_deduplication(self):
		self.assertEqual(notifications.parse_email_list("A@example.com\na@example.com,b@example.com"),
			["a@example.com", "b@example.com"])
		for value in ["invalid", "a@example.com,b@example.com", "Name <a@example.com>"]:
			self.assertIsNone(notifications.valid_email(value))

	def test_company_email_without_login(self):
		email, reason = notifications.resolve_employee_email(self.employee(company_email="company@example.com"))
		self.assertEqual(email, "company@example.com")
		self.assertIsNone(reason)

	def test_preferred_personal_email(self):
		email, _ = notifications.resolve_employee_email(self.employee(
			company_email="company@example.com", prefered_contact_email="Personal Email"))
		self.assertEqual(email, "hetiayasiwa@gmail.com")

	def test_invalid_company_falls_back_to_personal(self):
		email, _ = notifications.resolve_employee_email(self.employee(company_email="invalid"))
		self.assertEqual(email, "hetiayasiwa@gmail.com")

	def test_user_email_is_last_fallback(self):
		with patch.object(frappe, "db", MagicMock()) as db:
			db.get_value.return_value = frappe._dict(email="user@example.com", enabled=1)
			email, _ = notifications.resolve_employee_email(self.employee(
				user_id="user@example.com", personal_email=None))
		self.assertEqual(email, "user@example.com")

	def test_disabled_linked_user_is_skipped(self):
		with patch.object(frappe, "db", MagicMock()) as db:
			db.get_value.return_value = frappe._dict(email="user@example.com", enabled=0)
			email, reason = notifications.resolve_employee_email(self.employee(user_id="user@example.com"))
		self.assertIsNone(email)
		self.assertEqual(reason, "Linked user is disabled")

	def test_no_email(self):
		email, reason = notifications.resolve_employee_email(self.employee(personal_email=None))
		self.assertIsNone(email)
		self.assertEqual(reason, "No valid employee email")

	def plan(self, employee=None, settings=None, already_queued=False):
		with patch.object(frappe, "get_all", return_value=[employee or self.employee()]) as get_all:
			with patch.object(frappe, "db", MagicMock()) as db:
				db.get_value.return_value = None
				db.exists.return_value = already_queued
				plan = notifications.build_reminder_plan(settings or self.settings(), "2026-10-13")
				self.assertEqual(get_all.call_args.kwargs["filters"]["status"], "Active")
				self.assertIn("2026-10-16", [str(date) for date in
					get_all.call_args.kwargs["filters"]["contract_end_date"][1]])
		return plan

	def test_only_two_test_recipients(self):
		plan = self.plan()
		self.assertEqual([item["recipient"] for item in plan],
			["upalmrobot@gmail.com", "hetiayasiwa@gmail.com"])
		self.assertTrue(all(item["reminder_days"] == 3 and not item["skip_reason"] for item in plan))

	def test_allowlist_blocks_selected_email_without_fallback(self):
		plan = self.plan(employee=self.employee(company_email="outside@example.com"))
		self.assertEqual(plan[1]["recipient"], "outside@example.com")
		self.assertEqual(plan[1]["skip_reason"], "Recipient is outside test allowlist")

	def test_same_hr_employee_address_deduplicated(self):
		self.assertEqual(len(self.plan(employee=self.employee(personal_email="upalmrobot@gmail.com"))), 1)

	def test_already_queued(self):
		self.assertTrue(all(item["skip_reason"] == "Already queued"
			for item in self.plan(already_queued=True)))

	def test_contract_extension_changes_key(self):
		key = notifications.deduplication_key("EMP", "2026-10-16", 3, "a@example.com")
		self.assertNotEqual(key, notifications.deduplication_key("EMP", "2027-10-16", 3, "a@example.com"))

	def test_hr_html_template_escapes_data(self):
		item = self.plan()[0]
		item["employee_name"] = '<script>alert("test")</script>'
		with patch.object(notifications, "get_url_to_form", return_value="http://localhost/app/employee/EMP"):
			_, message = notifications.render_email(item)
		self.assertNotIn("<script>", message)
		self.assertIn("&lt;script&gt;", message)
		self.assertIn("ID Karyawan", message)
		self.assertIn("Perusahaan", message)
		self.assertNotIn("Departemen", message)
		self.assertIn('href="http://localhost/app/employee/EMP"', message)

	def test_employee_template_has_no_hr_details(self):
		with patch.object(notifications, "get_url_to_form") as url:
			subject, message = notifications.render_email(self.plan()[1])
		url.assert_not_called()
		self.assertEqual(subject, "Pengingat Masa Kontrak Kerja — Employee Test")
		self.assertIn("Silakan menghubungi HRD", message)
		self.assertIn("bukan keputusan mengenai perpanjangan", message)
		self.assertNotIn("href=", message)
		self.assertNotIn("ID Karyawan", message)

	def run_sender(self, settings, plan, sendmail=None):
		with patch.object(frappe, "get_single", return_value=settings):
			with patch.object(notifications, "build_reminder_plan", return_value=plan):
				with patch.object(notifications, "write_log") as log:
					with patch.object(frappe, "sendmail", sendmail or MagicMock()) as mail:
						with patch.object(frappe, "db", MagicMock()):
							result = notifications.send_contract_expiry_reminders()
						return result, log, mail

	def test_disabled_sends_nothing(self):
		result, log, mail = self.run_sender(self.settings(enabled=0), [])
		self.assertEqual(result, {"disabled": True})
		log.assert_not_called()
		mail.assert_not_called()

	def test_dry_run_never_sends_or_reserves_key(self):
		result, log, mail = self.run_sender(self.settings(), self.plan())
		self.assertEqual(result["dry_run"], 2)
		mail.assert_not_called()
		self.assertTrue(all("reserve" not in call.kwargs for call in log.call_args_list))

	def test_queue_separately_and_never_send_immediately(self):
		with patch.object(notifications, "get_url_to_form", return_value="http://localhost/app/employee/EMP"):
			result, log, mail = self.run_sender(self.settings(dry_run=0), self.plan())
		self.assertEqual(result["queued"], 2)
		self.assertTrue(all(call.kwargs["reserve"] for call in log.call_args_list))
		for call in mail.call_args_list:
			self.assertEqual(len(call.kwargs["recipients"]), 1)
			self.assertFalse(call.kwargs["now"])
			self.assertTrue(call.kwargs["delayed"])

	def test_queue_failure_rolls_back_reservation(self):
		with patch.object(frappe, "log_error"):
			with patch.object(notifications, "get_url_to_form", return_value="http://localhost"):
				result, log, _ = self.run_sender(self.settings(dry_run=0), self.plan(),
					MagicMock(side_effect=RuntimeError("Queue failed")))
		self.assertEqual(result["failed"], 2)
		self.assertEqual(log.call_args.args[1], "Failed")

	def test_preview_requires_hr_or_system_manager(self):
		with patch.object(frappe, "only_for", side_effect=PermissionError):
			with self.assertRaises(PermissionError):
				notifications.preview_contract_expiry_reminders()

	def test_test_plan_bypasses_schedule_and_existing_keys(self):
		with patch.object(frappe, "get_all", return_value=[self.employee()]) as get_all:
			with patch.object(frappe, "db", MagicMock()) as db:
				db.get_value.return_value = None
				db.exists.return_value = True
				plan = notifications.build_reminder_plan(self.settings(), "2026-10-12",
					test_employee="HR-EMP-00007")
				db.exists.assert_not_called()
		self.assertEqual(get_all.call_args.kwargs["filters"]["name"], "HR-EMP-00007")
		self.assertTrue(all(item["reminder_days"] == 4 and not item["skip_reason"] for item in plan))

	def test_test_plan_always_enforces_allowlist_and_permission(self):
		settings = self.settings(test_mode=0)
		with patch.object(frappe, "only_for") as permission:
			with patch.object(frappe, "get_doc") as document:
				with patch.object(frappe, "get_single", return_value=settings):
					with patch.object(notifications, "build_reminder_plan", return_value=self.plan()) as build:
						notifications.get_test_email_plan("HR-EMP-00007")
		permission.assert_called_once_with(["HR Manager"])
		document.return_value.check_permission.assert_called_once_with("read")
		self.assertEqual(build.call_args.args[0].test_mode, 1)
		self.assertEqual(build.call_args.kwargs["test_employee"], "HR-EMP-00007")

	def test_test_send_can_repeat_without_reserving_production_keys(self):
		with patch.object(notifications, "get_test_email_plan", return_value=self.plan()):
			with patch.object(notifications, "write_log") as log:
				with patch.object(frappe, "sendmail", return_value=frappe._dict(name="TEST-QUEUE")) as mail:
					with patch.object(frappe, "db", MagicMock()):
						with patch.object(notifications, "get_url_to_form", return_value="http://localhost"):
							for _ in range(2):
								result = notifications.send_test_email("HR-EMP-00007")
								self.assertEqual(len(result["queued"]), 2)
		self.assertEqual(mail.call_count, 4)
		for call in mail.call_args_list:
			self.assertTrue(call.kwargs["subject"].startswith("[TEST] "))
			self.assertIn("bukan pemberitahuan resmi", call.kwargs["message"])
			self.assertFalse(call.kwargs["now"])
			self.assertTrue(call.kwargs["delayed"])
		self.assertTrue(all("reserve" not in call.kwargs for call in log.call_args_list))

	def test_test_send_does_not_send_to_blocked_recipient(self):
		plan = self.plan(employee=self.employee(company_email="outside@example.com"))
		with patch.object(notifications, "get_test_email_plan", return_value=plan):
			with patch.object(notifications, "write_log"):
				with patch.object(frappe, "sendmail", return_value=frappe._dict(name="TEST-QUEUE")) as mail:
					with patch.object(frappe, "db", MagicMock()):
						with patch.object(notifications, "get_url_to_form", return_value="http://localhost"):
							result = notifications.send_test_email("HR-EMP-00007")
		self.assertEqual(mail.call_args.kwargs["recipients"], ["upalmrobot@gmail.com"])
		self.assertEqual(len(result["queued"]), 1)
		self.assertEqual(len(result["skipped"]), 1)

	def test_test_send_rolls_back_all_emails_on_failure(self):
		with patch.object(notifications, "get_test_email_plan", return_value=self.plan()):
			with patch.object(notifications, "write_log"):
				with patch.object(frappe, "sendmail", side_effect=[frappe._dict(name="TEST"), RuntimeError("Failed")]):
					with patch.object(frappe, "db", MagicMock()) as db:
						with patch.object(notifications, "get_url_to_form", return_value="http://localhost"):
							with self.assertRaises(RuntimeError):
								notifications.send_test_email("HR-EMP-00007")
						db.rollback.assert_called_once_with(save_point="contract_test_email")

	def test_test_action_rejects_unauthorized_user(self):
		with patch.object(frappe, "only_for", side_effect=PermissionError):
			with patch.object(frappe, "sendmail") as mail:
				with self.assertRaises(PermissionError):
					notifications.send_test_email("HR-EMP-00007")
				mail.assert_not_called()
