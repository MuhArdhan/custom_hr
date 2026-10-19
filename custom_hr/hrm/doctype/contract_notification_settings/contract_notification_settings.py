import frappe
from frappe.model.document import Document

from custom_hr.contract_notifications import parse_email_list, parse_reminder_days


class ContractNotificationSettings(Document):
	def validate(self):
		parse_reminder_days(self.reminder_days)
		parse_email_list(self.hr_recipients, strict=True)
		allowlist = parse_email_list(self.allowed_recipients, strict=True)
		if self.test_mode and not allowlist:
			frappe.throw("Allowlist penerima wajib diisi ketika Test Mode aktif.")
		if self.enabled and not parse_email_list(self.hr_recipients):
			frappe.throw("Isi minimal satu penerima HRD sebelum mengaktifkan notifikasi.")
