"""Daily contract reminders. Queueing and deduplication share one transaction."""

import hashlib
import re

import frappe
from frappe.utils import cint, date_diff, get_url_to_form, getdate, validate_email_address

SETTINGS = "Contract Notification Settings"
LOG = "Contract Notification Log"


def parse_reminder_days(value):
	try:
		days = sorted({int(part.strip()) for part in (value or "").split(",")})
	except ValueError:
		frappe.throw("Reminder Days harus berisi angka dipisahkan koma.")
	if not days or any(day < 0 for day in days):
		frappe.throw("Reminder Days tidak boleh kosong atau negatif.")
	return days


def valid_email(value):
	value = (value or "").strip().lower()
	# Accept exactly one address, never a list or a display-name header.
	if not value or re.search(r"[\s,;<>]", value):
		return None
	return value if validate_email_address(value) else None


def parse_email_list(value, strict=False):
	result = []
	for part in re.split(r"[,;\n]+", value or ""):
		if not part.strip():
			continue
		email = valid_email(part)
		if not email and strict:
			frappe.throw("Alamat email tidak valid: {0}".format(part.strip()))
		if email and email not in result:
			result.append(email)
	return result


def resolve_employee_email(employee):
	"""Respect the Employee preference, then company/personal email, then User."""
	user = None
	if employee.get("user_id"):
		user = frappe.db.get_value("User", employee.user_id, ["email", "enabled"], as_dict=True)
		if user and not cint(user.enabled):
			return None, "Linked user is disabled"

	user_email = user.email if user else None
	preferred = {
		"Company Email": employee.get("company_email"),
		"Personal Email": employee.get("personal_email"),
		"User ID": user_email,
	}.get(employee.get("prefered_contact_email"), employee.get("prefered_email"))
	for candidate in [preferred, employee.get("company_email"), employee.get("personal_email"), user_email]:
		if email := valid_email(candidate):
			return email, None
	return None, "No valid employee email"


def deduplication_key(employee, end_date, days, recipient):
	value = f"{employee}|{getdate(end_date).isoformat()}|{days}|{recipient.lower()}"
	return hashlib.sha256(value.encode()).hexdigest()


def build_reminder_plan(settings, today=None, *, test_employee=None):
	today = getdate(today)
	reminder_days = parse_reminder_days(settings.reminder_days)
	hr_emails = parse_email_list(settings.hr_recipients)
	allowlist = set(parse_email_list(settings.allowed_recipients))
	plan = []
	filters = {"status": "Active", "contract_end_date": ["in", [
		frappe.utils.add_days(today, day) for day in reminder_days
	]]}
	if test_employee:
		filters = {"name": test_employee, "status": "Active", "contract_end_date": [">=", today]}
	employees = frappe.get_all(
		"Employee",
		filters=filters,
		fields=["name", "employee_name", "contract_end_date", "company", "department",
			"user_id", "company_email", "personal_email", "prefered_contact_email", "prefered_email"],
		order_by="name",
	)
	for employee in employees:
		days = date_diff(employee.contract_end_date, today)
		email, reason = resolve_employee_email(employee)
		candidates = [(address, "HR", None) for address in hr_emails]
		candidates.append((email, "Employee", reason))
		seen = set()
		for recipient, recipient_type, skip_reason in candidates:
			if recipient and recipient in seen:
				continue
			seen.add(recipient)
			if recipient and cint(settings.test_mode) and recipient not in allowlist:
				skip_reason = "Recipient is outside test allowlist"
			if recipient:
				account = frappe.db.get_value("User", {"email": recipient}, ["name", "enabled"], as_dict=True)
				if account and not cint(account.enabled):
					skip_reason = "Recipient user is disabled"
			key = deduplication_key(employee.name, employee.contract_end_date, days, recipient) if recipient else None
			if not test_employee and key and frappe.db.exists(LOG, {"deduplication_key": key}):
				skip_reason = "Already queued"
			plan.append({
				"employee": employee.name, "employee_name": employee.employee_name,
				"contract_end_date": str(employee.contract_end_date), "reminder_days": days,
				"recipient": recipient, "recipient_type": recipient_type,
				"company": employee.company, "department": employee.department,
				"skip_reason": skip_reason, "deduplication_key": key,
			})
	return plan


@frappe.whitelist()
def preview_contract_expiry_reminders():
	frappe.only_for(["HR Manager", "System Manager"])
	settings = frappe.get_single(SETTINGS)
	return {"enabled": cint(settings.enabled), "dry_run": cint(settings.dry_run),
		"date": str(getdate()), "reminders": build_reminder_plan(settings)}


def get_test_email_plan(employee):
	frappe.only_for(["HR Manager"])
	if not employee:
		frappe.throw("Pilih karyawan untuk pengujian.")
	frappe.get_doc("Employee", employee).check_permission("read")
	settings = frappe.get_single(SETTINGS)
	if not parse_email_list(settings.allowed_recipients):
		frappe.throw("Isi Allowed Recipients sebelum mengirim email test.")
	# Tests always enforce the allowlist, even if production Test Mode is off.
	settings.test_mode = 1
	plan = build_reminder_plan(settings, test_employee=employee)
	if not plan:
		frappe.throw("Pilih karyawan aktif dengan Contract End Date hari ini atau setelahnya.")
	return plan


@frappe.whitelist()
def preview_test_email(employee):
	return {"reminders": get_test_email_plan(employee)}


@frappe.whitelist(methods=["POST"])
def send_test_email(employee):
	"""Explicit action: real test emails independent of Enabled/Dry Run.

	Never reserve production keys. Recipients are recalculated server-side and
	constrained to the saved allowlist on every request.
	"""
	plan = get_test_email_plan(employee)
	eligible = [item for item in plan if not item["skip_reason"]]
	if not eligible:
		frappe.throw("Tidak ada penerima test yang valid dalam allowlist.")
	queued = []
	frappe.db.savepoint("contract_test_email")
	try:
		for item in eligible:
			subject, message = render_email({**item, "is_test": True})
			queue = frappe.sendmail(
				recipients=[item["recipient"]], subject=f"[TEST] {subject}", message=message,
				reference_doctype="Employee", reference_name=item["employee"],
				now=False, delayed=True,
			)
			if not queue:
				raise RuntimeError("Email Queue was not created")
			write_log(item, "Queued", f"[TEST] Email Queue: {queue.name}. No production key reserved.")
			queued.append({"recipient": item["recipient"], "email_queue": queue.name})
	except Exception:
		frappe.db.rollback(save_point="contract_test_email")
		raise
	return {"queued": queued, "skipped": [item for item in plan if item["skip_reason"]]}


def render_email(item):
	is_hr = item["recipient_type"] == "HR"
	employee_name = item["employee_name"] or item["employee"]
	subject_prefix = "Tindak Lanjut Kontrak Karyawan" if is_hr else "Pengingat Masa Kontrak Kerja"
	subject = f"{subject_prefix} — {employee_name}"
	template = "contract_expiry_hr.html" if is_hr else "contract_expiry_employee.html"
	context = {
		**item,
		"employee_name": item["employee_name"] or item["employee"],
		"employee_url": get_url_to_form("Employee", item["employee"]) if is_hr else None,
	}
	message = frappe.render_template(f"templates/emails/{template}", context)
	return subject, message


def write_log(item, status, details=None, reserve=False):
	return frappe.get_doc({
		"doctype": LOG, "employee": item["employee"],
		"contract_end_date": item["contract_end_date"], "reminder_days": item["reminder_days"],
		"recipient": item["recipient"], "recipient_type": item["recipient_type"],
		"status": status, "details": details,
		"deduplication_key": item["deduplication_key"] if reserve else None,
	}).insert(ignore_permissions=True)


def send_contract_expiry_reminders():
	settings = frappe.get_single(SETTINGS)
	if not cint(settings.enabled):
		return {"disabled": True}
	result = {"queued": 0, "dry_run": 0, "skipped": 0, "failed": 0}
	for item in build_reminder_plan(settings):
		if item["skip_reason"]:
			write_log(item, "Skipped", item["skip_reason"])
			result["skipped"] += 1
			continue
		if cint(settings.dry_run):
			write_log(item, "Dry Run", "No email queued; preview only")
			result["dry_run"] += 1
			continue
		frappe.db.savepoint("contract_reminder")
		try:
			write_log(item, "Queued", "Delivery status is available in Email Queue", reserve=True)
			subject, message = render_email(item)
			queue = frappe.sendmail(
				recipients=[item["recipient"]], subject=subject, message=message,
				reference_doctype="Employee", reference_name=item["employee"],
				now=False, delayed=True,
			)
			if not queue:
				raise RuntimeError("Email Queue was not created")
		except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
			frappe.db.rollback(save_point="contract_reminder")
			result["skipped"] += 1
		except Exception:
			frappe.db.rollback(save_point="contract_reminder")
			frappe.log_error(title="Contract reminder queue failed", message=frappe.get_traceback())
			write_log(item, "Failed", "Queueing failed; see Error Log. Retry is allowed.")
			result["failed"] += 1
		else:
			result["queued"] += 1
	return result
