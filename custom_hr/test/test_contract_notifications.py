import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import frappe
from jinja2 import Environment, FileSystemLoader

from custom_hr import contract_notifications as notifications


class TestContractNotifications(unittest.TestCase):
	def setUp(self):
		config = patch.object(frappe, "conf", frappe._dict())
		config.start()
		self.addCleanup(config.stop)
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

	def two_employee_plan(self):
		first = self.plan()
		second = [{**item, "employee": "HR-EMP-00008", "employee_name": "Second Employee",
			"recipient": item["recipient"] if item["recipient_type"] == "HR" else "second@example.com",
			"deduplication_key": "second-" + item["deduplication_key"]} for item in first]
		return first + second

	def test_hr_same_stage_grouped_employee_emails_separate(self):
		plan = self.two_employee_plan()
		with patch.object(notifications, "get_url_to_form", return_value="http://localhost"):
			result, log, mail = self.run_sender(self.settings(dry_run=0), plan)
		self.assertEqual(result["queued"], 3)
		self.assertEqual(log.call_count, 4)
		hr_calls = [call for call in mail.call_args_list if call.kwargs["recipients"] == ["upalmrobot@gmail.com"]]
		self.assertEqual(len(hr_calls), 1)
		self.assertIn("Employee Test", hr_calls[0].kwargs["message"])
		self.assertIn("Second Employee", hr_calls[0].kwargs["message"])
		self.assertIn("H-3", hr_calls[0].kwargs["subject"])
		self.assertEqual(hr_calls[0].kwargs["reference_doctype"], notifications.SETTINGS)
		for call in mail.call_args_list:
			if call.kwargs["recipients"] == ["hetiayasiwa@gmail.com"]:
				self.assertNotIn("Second Employee", call.kwargs["message"])
			elif call.kwargs["recipients"] == ["second@example.com"]:
				self.assertNotIn("Employee Test", call.kwargs["message"])

	def test_hr_different_stages_and_recipients_not_grouped(self):
		first = self.plan()[0]
		items = [first, {**first, "reminder_days": 7, "contract_end_date": "2026-10-20"},
			{**first, "recipient": "otherhr@example.com"}]
		self.assertEqual(len(notifications.group_reminders(items)), 3)

	def test_hr_summary_escapes_employee_data(self):
		items = [item for item in self.two_employee_plan() if item["recipient_type"] == "HR"]
		items[1]["employee_name"] = "<script>unsafe</script>"
		with patch.object(notifications, "get_url_to_form", return_value="http://localhost"):
			_, message = notifications.render_reminder_group(items)
		self.assertNotIn("<script>", message)
		self.assertIn("&lt;script&gt;unsafe&lt;/script&gt;", message)

	def test_group_failure_does_not_keep_any_reserved_keys(self):
		items = [item for item in self.two_employee_plan() if item["recipient_type"] == "HR"]
		with patch.object(frappe, "log_error"):
			with patch.object(notifications, "get_url_to_form", return_value="http://localhost"):
				result, log, _ = self.run_sender(self.settings(dry_run=0), items,
					MagicMock(side_effect=RuntimeError("Queue failed")))
		self.assertEqual(result["failed"], 2)
		failed_logs = [call for call in log.call_args_list if call.args[1] == "Failed"]
		self.assertEqual(len(failed_logs), 2)
		self.assertTrue(all("reserve" not in call.kwargs for call in failed_logs))

	def test_concurrent_duplicate_does_not_skip_remaining_group_members(self):
		items = [item for item in self.two_employee_plan() if item["recipient_type"] == "HR"]
		with patch.object(frappe, "get_single", return_value=self.settings(dry_run=0)):
			with patch.object(notifications, "build_reminder_plan", return_value=items):
				with patch.object(notifications, "write_log", side_effect=[frappe.UniqueValidationError(), None]):
					with patch.object(frappe, "db", MagicMock()) as db:
						with patch.object(frappe, "sendmail", return_value=MagicMock()) as mail:
							with patch.object(notifications, "get_url_to_form", return_value="http://localhost"):
								result = notifications.send_contract_expiry_reminders()
		self.assertEqual(result["skipped"], 1)
		self.assertEqual(result["queued"], 1)
		self.assertNotIn("Employee Test", mail.call_args.kwargs["message"])
		self.assertIn("Second Employee", mail.call_args.kwargs["message"])
		db.rollback.assert_called_once_with(save_point="contract_reminder_item")

	def test_multi_employee_test_selection_accepts_json_and_removes_duplicates(self):
		settings = self.settings(test_mode=0)
		with patch.object(frappe, "only_for"):
			with patch.object(frappe, "get_doc") as documents:
				with patch.object(frappe, "get_single", return_value=settings):
					with patch.object(notifications, "build_reminder_plan", side_effect=[self.plan(), self.plan()]) as build:
						plan = notifications.get_test_email_plan(
							employees='["HR-EMP-00007", "HR-EMP-00008", "HR-EMP-00007"]')
		self.assertEqual(len(plan), 4)
		self.assertEqual(documents.call_count, 2)
		self.assertEqual([call.kwargs["test_employee"] for call in build.call_args_list],
			["HR-EMP-00007", "HR-EMP-00008"])
		self.assertTrue(all(call.args[0].test_mode == 1 for call in build.call_args_list))

	def test_multi_employee_test_sends_hr_summary_and_individual_employee_emails(self):
		with patch.object(notifications, "get_test_email_plan", return_value=self.two_employee_plan()):
			with patch.object(notifications, "write_log") as log:
				with patch.object(frappe, "sendmail", return_value=frappe._dict(name="TEST-QUEUE")) as mail:
					with patch.object(frappe, "db", MagicMock()):
						with patch.object(notifications, "get_url_to_form", return_value="http://localhost"):
							result = notifications.send_test_email(employees=["HR-EMP-00007", "HR-EMP-00008"])
		self.assertEqual(len(result["queued"]), 3)
		self.assertEqual(mail.call_count, 3)
		self.assertEqual(log.call_count, 4)
		hr = [call for call in mail.call_args_list if call.kwargs["recipients"] == ["upalmrobot@gmail.com"]]
		self.assertEqual(len(hr), 1)
		self.assertIn("Employee Test", hr[0].kwargs["message"])
		self.assertIn("Second Employee", hr[0].kwargs["message"])
		self.assertIn("bukan pemberitahuan resmi", hr[0].kwargs["message"])
		self.assertTrue(hr[0].kwargs["subject"].startswith("[TEST] "))
		self.assertTrue(all("reserve" not in call.kwargs for call in log.call_args_list))

	def test_department_not_shown_even_when_populated(self):
		items = [{**item, "department": "Secret Department"}
			for item in self.two_employee_plan() if item["recipient_type"] == "HR"]
		with patch.object(notifications, "get_url_to_form", return_value="http://localhost"):
			_, single = notifications.render_email(items[0])
			_, summary = notifications.render_reminder_group(items)
		for message in [single, summary]:
			self.assertNotIn("Departemen", message)
			self.assertNotIn("Secret Department", message)

	def test_multi_employee_selection_rejects_invalid_input(self):
		with patch.object(frappe, "only_for"):
			with patch.object(frappe, "throw", side_effect=ValueError):
				for selection in [[], {}, [123], [""], [f"EMP-{i}" for i in range(51)]]:
					with self.subTest(selection=selection), self.assertRaises(ValueError):
						notifications.get_test_email_plan(employees=selection)

	def test_employee_email_url_uses_public_host_without_development_port(self):
		with patch.object(frappe, "conf", frappe._dict(host_name="active.ngrok-free.dev")):
			with patch.object(notifications, "get_url_to_form",
				return_value="http://active.ngrok-free.dev:8000/desk/employee/EMP-1"):
				self.assertEqual(notifications.get_employee_email_url("EMP-1"),
					"https://active.ngrok-free.dev/desk/employee/EMP-1")

	def test_employee_email_url_respects_explicit_scheme_and_port(self):
		with patch.object(frappe, "conf", frappe._dict(host_name="http://hr.example.com:8080")):
			with patch.object(notifications, "get_url_to_form", return_value="http://old:8000/desk/employee/EMP-1"):
				self.assertEqual(notifications.get_employee_email_url("EMP-1"),
					"http://hr.example.com:8080/desk/employee/EMP-1")

	def test_employee_email_url_keeps_local_port(self):
		url = "http://development.localhost:8000/desk/employee/EMP-1"
		with patch.object(frappe, "conf", frappe._dict(host_name="development.localhost")):
			with patch.object(notifications, "get_url_to_form", return_value=url):
				self.assertEqual(notifications.get_employee_email_url("EMP-1"), url)

	def test_local_site_ignores_stale_ngrok_hostname(self):
		with patch.object(frappe, "local", frappe._dict(site="development.localhost")):
			with patch.object(frappe, "conf", frappe._dict(host_name="stale.ngrok-free.dev", webserver_port=8000)):
				with patch.object(notifications, "get_url_to_form",
					return_value="http://stale.ngrok-free.dev:8000/desk/employee/EMP-1"):
					self.assertEqual(notifications.get_employee_email_url("EMP-1"),
						"http://development.localhost:8000/desk/employee/EMP-1")

	def test_cloud_site_uses_its_domain_when_host_name_is_unset(self):
		with patch.object(frappe, "local", frappe._dict(site="company.frappe.cloud")):
			with patch.object(frappe, "conf", frappe._dict()):
				with patch.object(notifications, "get_url_to_form",
					return_value="http://company.frappe.cloud/desk/employee/EMP-1"):
					self.assertEqual(notifications.get_employee_email_url("EMP-1"),
						"https://company.frappe.cloud/desk/employee/EMP-1")

	def test_cloud_site_uses_configured_custom_domain(self):
		with patch.object(frappe, "local", frappe._dict(site="company.frappe.cloud")):
			with patch.object(frappe, "conf", frappe._dict(host_name="https://hr.company.com")):
				with patch.object(notifications, "get_url_to_form",
					return_value="https://hr.company.com/desk/employee/EMP-1"):
					self.assertEqual(notifications.get_employee_email_url("EMP-1"),
						"https://hr.company.com/desk/employee/EMP-1")
