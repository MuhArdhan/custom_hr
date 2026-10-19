"""Daily contract reminders. Queueing and deduplication share one transaction."""

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

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
		fields=["name", "employee_name", "contract_end_date", "company",
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
				"company": employee.company,
				"skip_reason": skip_reason, "deduplication_key": key,
			})
	return plan


@frappe.whitelist()
def preview_contract_expiry_reminders():
	frappe.only_for(["HR Manager", "System Manager"])
	settings = frappe.get_single(SETTINGS)
	plan = build_reminder_plan(settings)
	groups = group_reminders([item for item in plan if not item["skip_reason"]])
	return {"enabled": cint(settings.enabled), "dry_run": cint(settings.dry_run),
		"date": str(getdate()), "reminders": plan,
		"email_groups": [{"recipient": group[0]["recipient"],
			"recipient_type": group[0]["recipient_type"],
			"contract_end_date": group[0]["contract_end_date"],
			"reminder_days": group[0]["reminder_days"],
			"employees": [item["employee"] for item in group]} for group in groups]}


def get_test_email_plan(employee=None, *, employees=None):
	frappe.only_for(["HR Manager"])
	if employees is not None and employee:
		frappe.throw("Gunakan employee atau employees, bukan keduanya.")
	if employees is None:
		employees = [employee] if employee else []
	elif isinstance(employees, str):
		employees = frappe.parse_json(employees)
	if not isinstance(employees, list) or any(not isinstance(name, str) or not name.strip() for name in employees):
		frappe.throw("Daftar karyawan tidak valid.")
	employees = list(dict.fromkeys(employees))
	if not employees:
		frappe.throw("Pilih karyawan untuk pengujian.")
	if len(employees) > 50:
		frappe.throw("Maksimal 50 karyawan dalam satu pengujian.")
	for name in employees:
		frappe.get_doc("Employee", name).check_permission("read")
	settings = frappe.get_single(SETTINGS)
	if not parse_email_list(settings.allowed_recipients):
		frappe.throw("Isi Allowed Recipients sebelum mengirim email test.")
	# Tests always enforce the allowlist, even if production Test Mode is off.
	settings.test_mode = 1
	plan = []
	for name in employees:
		items = build_reminder_plan(settings, test_employee=name)
		if not items:
			frappe.throw("Karyawan {0} harus aktif dan memiliki Contract End Date hari ini atau setelahnya.".format(name))
		plan.extend(items)
	return plan


@frappe.whitelist()
def preview_test_email(employee=None, employees=None):
	plan = get_test_email_plan(employee, employees=employees)
	groups = group_reminders([item for item in plan if not item["skip_reason"]])
	return {"reminders": plan, "email_groups": [
		{"recipient": group[0]["recipient"], "recipient_type": group[0]["recipient_type"],
			"reminder_days": group[0]["reminder_days"], "employees": [item["employee"] for item in group]}
		for group in groups]}


@frappe.whitelist(methods=["POST"])
def send_test_email(employee=None, employees=None):
	"""Explicit action: real test emails independent of Enabled/Dry Run.

	Never reserve production keys. Recipients are recalculated server-side and
	constrained to the saved allowlist on every request.
	"""
	plan = get_test_email_plan(employee, employees=employees)
	eligible = [item for item in plan if not item["skip_reason"]]
	if not eligible:
		frappe.throw("Tidak ada penerima test yang valid dalam allowlist.")
	queued = []
	frappe.db.savepoint("contract_test_email")
	try:
		for group in group_reminders(eligible):
			item = group[0]
			is_summary = len(group) > 1
			subject, message = render_reminder_group(group, is_test=True)
			queue = frappe.sendmail(
				recipients=[item["recipient"]], subject=f"[TEST] {subject}", message=message,
				reference_doctype=SETTINGS if is_summary else "Employee",
				reference_name=SETTINGS if is_summary else item["employee"],
				now=False, delayed=True,
			)
			if not queue:
				raise RuntimeError("Email Queue was not created")
			for reminder in group:
				write_log(reminder, "Queued", f"[TEST] Email Queue: {queue.name}. No production key reserved.")
			queued.append({"recipient": item["recipient"], "email_queue": queue.name,
				"employees": [reminder["employee"] for reminder in group]})
	except Exception:
		frappe.db.rollback(save_point="contract_test_email")
		raise
	return {"queued": queued, "skipped": [item for item in plan if item["skip_reason"]]}


def get_employee_email_url(employee):
	"""Local sites use their local address; cloud sites use their canonical host."""
	url = get_url_to_form("Employee", employee)
	site = getattr(frappe.local, "site", None)
	if site and (site == "localhost" or site.endswith(".localhost")):
		# Do not inherit an old tunnel's host_name on the local development site.
		port = frappe.conf.get("http_port") or frappe.conf.get("webserver_port") or 8000
		return urlunsplit(("http", f"{site}:{port}", urlsplit(url).path, "", ""))
	host = frappe.conf.get("host_name") or frappe.conf.get("hostname") or site
	if not host:
		return url
	configured = urlsplit(host if "://" in host else f"//{host}")
	hostname = (configured.hostname or "").lower()
	if not hostname:
		return url
	is_local = hostname in ("localhost", "127.0.0.1", "::1") or hostname.endswith(".localhost")
	if is_local and not configured.port:
		return url
	# A public hostname without a scheme defaults to HTTPS. Explicit scheme/port
	# remain authoritative; e.g. ngrok HTTPS uses no internal :8000 suffix.
	scheme = configured.scheme or ("http" if is_local else "https")
	return urlunsplit((scheme, configured.netloc, urlsplit(url).path, "", ""))


def render_email(item):
	is_hr = item["recipient_type"] == "HR"
	employee_name = item["employee_name"] or item["employee"]
	subject_prefix = "Tindak Lanjut Kontrak Karyawan" if is_hr else "Pengingat Masa Kontrak Kerja"
	subject = f"{subject_prefix} — {employee_name}"
	template = "contract_expiry_hr.html" if is_hr else "contract_expiry_employee.html"
	context = {
		**item,
		"employee_name": item["employee_name"] or item["employee"],
		"employee_url": get_employee_email_url(item["employee"]) if is_hr else None,
	}
	message = frappe.render_template(f"templates/emails/{template}", context)
	return subject, message


def group_reminders(items):
	"""Group HR reminders by recipient and expiry stage; keep employees private."""
	groups = []
	hr_groups = {}
	for item in items:
		if item["recipient_type"] != "HR":
			groups.append([item])
			continue
		key = (item["recipient"], item["contract_end_date"], item["reminder_days"])
		if key not in hr_groups:
			hr_groups[key] = []
			groups.append(hr_groups[key])
		hr_groups[key].append(item)
	return groups


def render_reminder_group(items, *, is_test=False):
	if len(items) == 1:
		return render_email({**items[0], "is_test": is_test})
	first = items[0]
	subject = "Tindak Lanjut Kontrak Karyawan — {0} karyawan (H-{1}, {2})".format(
		len(items), first["reminder_days"], first["contract_end_date"]
	)
	context = {
		"is_test": is_test,
		"contract_end_date": first["contract_end_date"],
		"reminder_days": first["reminder_days"],
		"employees": [{**item, "employee_url": get_employee_email_url(item["employee"])} for item in items],
	}
	return subject, frappe.render_template("templates/emails/contract_expiry_hr_summary.html", context)


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
	eligible = []
	for item in build_reminder_plan(settings):
		if item["skip_reason"]:
			write_log(item, "Skipped", item["skip_reason"])
			result["skipped"] += 1
			continue
		if cint(settings.dry_run):
			write_log(item, "Dry Run", "No email queued; preview only")
			result["dry_run"] += 1
			continue
		eligible.append(item)
	for group in group_reminders(eligible):
		frappe.db.savepoint("contract_reminder")
		reserved = []
		duplicates = []
		try:
			for item in group:
				frappe.db.savepoint("contract_reminder_item")
				try:
					write_log(item, "Queued", "Delivery status is available in Email Queue", reserve=True)
				except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
					frappe.db.rollback(save_point="contract_reminder_item")
					duplicates.append(item)
					result["skipped"] += 1
				else:
					reserved.append(item)
			if not reserved:
				continue
			subject, message = render_reminder_group(reserved)
			first = reserved[0]
			is_summary = len(reserved) > 1
			queue = frappe.sendmail(
				recipients=[first["recipient"]], subject=subject, message=message,
				reference_doctype=SETTINGS if is_summary else "Employee",
				reference_name=SETTINGS if is_summary else first["employee"],
				now=False, delayed=True,
			)
			if not queue:
				raise RuntimeError("Email Queue was not created")
		except Exception:
			frappe.db.rollback(save_point="contract_reminder")
			frappe.log_error(title="Contract reminder queue failed", message=frappe.get_traceback())
			for item in group:
				if item not in duplicates:
					write_log(item, "Failed", "Queueing failed; see Error Log. Retry is allowed.")
					result["failed"] += 1
		else:
			result["queued"] += 1
	return result
