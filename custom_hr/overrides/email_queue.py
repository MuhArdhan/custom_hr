"""Local SMTP delivery without changing the installed cloud delivery service.

The cloud delivery hook takes priority over native SMTP in Frappe. Override the
queue's delivery method locally, while retaining the normal queue lifecycle.
"""

import frappe
from frappe.email.doctype.email_queue.email_queue import EmailQueue, SendMailContext
from frappe.utils import get_hook_method


def get_email_transport():
	config = frappe.get_site_config()
	transport = config.get("custom_hr_email_transport", "auto")
	if transport not in ("auto", "smtp", "email_delivery_service"):
		frappe.throw("custom_hr_email_transport must be auto, smtp, or email_delivery_service.")
	if transport == "auto":
		site = frappe.local.site.lower()
		if site == "localhost" or site.endswith(".localhost"):
			return "smtp"
		if config.get("sk_email_delivery_service"):
			transport = "email_delivery_service"
		else:
			frappe.throw("Configure custom_hr_email_transport explicitly for a non-local site.")
	if transport == "email_delivery_service":
		if not config.get("sk_email_delivery_service"):
			frappe.throw("Email Delivery Service credentials are missing.")
		if "email_delivery_service" not in frappe.get_installed_apps():
			frappe.throw("Email Delivery Service is not installed.")
		from email_delivery_service.controller import send

		if get_hook_method("override_email_send") != send:
			frappe.throw("Email Delivery Service is not the active email delivery hook.")
	return transport


class CustomEmailQueue(EmailQueue):
	def send(self, smtp_server_instance=None, frappe_mail_client=None, force_send=False):
		if get_email_transport() == "smtp":
			return send_via_smtp(self, smtp_server_instance, force_send)
		return super().send(
			smtp_server_instance=smtp_server_instance,
			frappe_mail_client=frappe_mail_client,
			force_send=force_send,
		)


def send_via_smtp(queue, smtp_server_instance=None, force_send=False):
	if not queue.can_send_now() and not force_send:
		return
	with SendMailContext(queue, smtp_server_instance=smtp_server_instance) as ctx:
		ctx.fetch_outgoing_server()
		if ctx.email_account_doc.service == "Frappe Mail":
			frappe.throw("Local SMTP mode requires an SMTP Email Account, not Frappe Mail.")
		last_message = None
		for recipient in queue.recipients:
			if recipient.is_mail_sent():
				continue
			message = ctx.build_message(recipient.recipient)
			last_message = message
			if not frappe.in_test or frappe.flags.testing_email:
				msg = message if isinstance(message, bytes) else message.encode("utf-8")
				session = ctx.smtp_server.session
				if session.has_extn("SIZE"):
					max_size = int(session.esmtp_features.get("size") or 0)
					if max_size > 0 and len(msg) > max_size:
						frappe.throw("Email exceeds the SMTP server's maximum message size.")
				mail_options, rcpt_options = [], []
				if session.has_extn("DSN") and ctx.email_account_doc.dsn_notify_type:
					mail_options = ["RET=FULL", f"ENVID={queue.name}"]
					rcpt_options = [f"NOTIFY={ctx.email_account_doc.dsn_notify_type}"]
				refused = session.sendmail(
					from_addr=queue.sender, to_addrs=recipient.recipient, msg=msg,
					mail_options=mail_options, rcpt_options=rcpt_options,
				)
				if refused:
					raise RuntimeError("SMTP server refused the recipient")
			ctx.update_recipient_status_to_sent(recipient)
		if frappe.in_test and not frappe.flags.testing_email:
			frappe.flags.sent_mail = last_message
			return
		if last_message and ctx.email_account_doc.append_emails_to_sent_folder:
			ctx.email_account_doc.append_email_to_sent_folder(last_message)
