import unittest
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.overrides import email_queue as delivery


class TestEmailTransport(unittest.TestCase):
	def transport(self, config, site="development.localhost"):
		with patch.object(frappe, "get_site_config", return_value=config):
			with patch.object(frappe, "local", frappe._dict(site=site)):
				return delivery.get_email_transport()

	def test_localhost_uses_smtp_even_if_cloud_key_exists(self):
		self.assertEqual(self.transport({"sk_email_delivery_service": "test-key"}), "smtp")

	def test_explicit_smtp_on_other_hostname(self):
		self.assertEqual(self.transport({"custom_hr_email_transport": "smtp"}, "local.test"), "smtp")

	def test_unknown_site_fails_closed(self):
		with patch.object(frappe, "throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				self.transport({}, "example.com")

	def test_cloud_requires_credentials(self):
		with patch.object(frappe, "throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				self.transport({"custom_hr_email_transport": "email_delivery_service"})

	def test_cloud_requires_app(self):
		with patch.object(frappe, "get_installed_apps", return_value=[]):
			with patch.object(frappe, "throw", side_effect=ValueError):
				with self.assertRaises(ValueError):
					self.transport({"sk_email_delivery_service": "test-key"}, "example.frappe.cloud")

	def test_cloud_delegates_to_existing_service(self):
		from email_delivery_service.controller import send

		with patch.object(frappe, "get_installed_apps", return_value=["email_delivery_service"]):
			with patch.object(delivery, "get_hook_method", return_value=send):
				self.assertEqual(self.transport({"sk_email_delivery_service": "test-key"},
					"example.frappe.cloud"), "email_delivery_service")

	def test_queue_cloud_path_uses_native_send(self):
		queue = object.__new__(delivery.CustomEmailQueue)
		with patch.object(delivery, "get_email_transport", return_value="email_delivery_service"):
			with patch.object(delivery.EmailQueue, "send", return_value="cloud") as send:
				self.assertEqual(queue.send(force_send=True), "cloud")
				send.assert_called_once_with(smtp_server_instance=None, frappe_mail_client=None, force_send=True)

	def test_queue_local_path_bypasses_cloud(self):
		queue = object.__new__(delivery.CustomEmailQueue)
		with patch.object(delivery, "get_email_transport", return_value="smtp"):
			with patch.object(delivery, "send_via_smtp") as smtp:
				with patch.object(delivery.EmailQueue, "send") as cloud:
					queue.send()
					smtp.assert_called_once_with(queue, None, False)
					cloud.assert_not_called()

	def test_smtp_sends_and_updates_status_without_network(self):
		queue = MagicMock()
		queue.sender = "sender@example.com"
		recipient = MagicMock()
		recipient.recipient = "test@example.com"
		recipient.is_mail_sent.return_value = False
		queue.recipients = [recipient]
		ctx = MagicMock()
		ctx.__enter__.return_value = ctx
		ctx.email_account_doc.service = "GMail"
		ctx.email_account_doc.append_emails_to_sent_folder = False
		ctx.build_message.return_value = "Subject: Test\n\nTest"
		ctx.smtp_server.session.has_extn.return_value = False
		ctx.smtp_server.session.sendmail.return_value = {}
		with patch.object(delivery, "SendMailContext", return_value=ctx):
			with patch.object(frappe, "in_test", False):
				delivery.send_via_smtp(queue)
		ctx.smtp_server.session.sendmail.assert_called_once_with(
			from_addr="sender@example.com", to_addrs="test@example.com",
			msg=b"Subject: Test\n\nTest", mail_options=[], rcpt_options=[])
		ctx.update_recipient_status_to_sent.assert_called_once_with(recipient)

	def test_smtp_failure_does_not_mark_recipient_sent(self):
		queue = MagicMock()
		recipient = MagicMock()
		recipient.is_mail_sent.return_value = False
		queue.recipients = [recipient]
		ctx = MagicMock()
		ctx.__enter__.return_value = ctx
		ctx.email_account_doc.service = "GMail"
		ctx.build_message.return_value = "Test"
		ctx.smtp_server.session.has_extn.return_value = False
		ctx.smtp_server.session.sendmail.side_effect = RuntimeError("SMTP failed")
		with patch.object(delivery, "SendMailContext", return_value=ctx):
			with patch.object(frappe, "in_test", False):
				with self.assertRaises(RuntimeError):
					delivery.send_via_smtp(queue)
		ctx.update_recipient_status_to_sent.assert_not_called()
