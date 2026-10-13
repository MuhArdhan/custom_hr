"""Contract administration only; does not update Employee or send notifications."""

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, add_months, cint, getdate

DURATION_MONTHS = {"3 bulan": 3, "6 bulan": 6, "12 bulan": 12, "24 bulan": 24}


def get_duration_end_date(start_date, duration):
	months = DURATION_MONTHS.get(duration)
	if not months or not start_date:
		return None
	return getdate(add_days(add_months(getdate(start_date), months), -1))


def get_contract_status(doc, today=None):
	if cint(doc.docstatus) == 2:
		return "Dibatalkan"
	if cint(doc.docstatus) == 0:
		return "Draft"
	today = getdate(today)
	if getdate(doc.start_date) > today:
		return "Belum Berlaku"
	if doc.end_date and getdate(doc.end_date) < today:
		return "Berakhir"
	return "Aktif"


class EmployeeContract(Document):
	@property
	def contract_status(self):
		return get_contract_status(self)

	def validate(self):
		self.validate_dates()
		self.validate_previous_contract()
		if self.contract_file:
			self.validate_private_file()
		if self.is_new() or self.has_value_changed("employee"):
			employee = frappe.get_doc("Employee", self.employee)
			employee.check_permission("read")
			self.employee_name = employee.employee_name
			self.company = employee.company
			self.department = employee.department

	def validate_dates(self):
		if not self.start_date:
			frappe.throw("Tanggal mulai kontrak wajib diisi.")
		if self.contract_type not in ("PKWT", "PKWTT"):
			frappe.throw("Jenis kontrak harus PKWT atau PKWTT.")
		duration = self.get("contract_duration") or "Custom"
		if duration != "Custom" and duration not in DURATION_MONTHS:
			frappe.throw("Durasi kontrak tidak valid.")
		if self.contract_type == "PKWT" and duration in DURATION_MONTHS:
			expected_end = get_duration_end_date(self.start_date, duration)
			if not self.end_date:
				self.end_date = expected_end
			elif getdate(self.end_date) != expected_end:
				frappe.throw("Tanggal akhir tidak sesuai durasi. Pilih Custom untuk tanggal akhir manual.")
		if self.contract_type == "PKWT" and not self.end_date:
			frappe.throw("Tanggal akhir wajib diisi untuk PKWT.")
		if self.contract_type == "PKWTT" and self.end_date:
			frappe.throw("PKWTT tidak memiliki tanggal akhir. Kosongkan Tanggal Akhir.")
		if self.end_date and getdate(self.end_date) < getdate(self.start_date):
			frappe.throw("Tanggal akhir tidak boleh sebelum tanggal mulai.")

	def validate_private_file(self):
		if not self.contract_file.startswith("/private/files/"):
			frappe.throw("Dokumen kontrak harus diunggah sebagai private file.")
		file = frappe.db.get_value("File", {"file_url": self.contract_file, "is_private": 1}, "name")
		if not file:
			frappe.throw("Dokumen kontrak private tidak ditemukan.")
		frappe.get_doc("File", file).check_permission("read")

	def validate_previous_contract(self):
		if not self.previous_contract:
			return
		if self.previous_contract == self.name:
			frappe.throw("Kontrak sebelumnya tidak boleh menunjuk ke kontrak ini sendiri.")
		previous = frappe.get_doc("Employee Contract", self.previous_contract)
		previous.check_permission("read")
		if previous.docstatus != 1 or previous.employee != self.employee:
			frappe.throw("Kontrak sebelumnya harus sudah Submit dan milik karyawan yang sama.")
		if previous.contract_type != "PKWT" or not previous.end_date:
			frappe.throw("Hanya kontrak PKWT yang dapat diperpanjang.")
		if getdate(self.start_date) <= getdate(previous.end_date):
			frappe.throw("Perpanjangan harus dimulai setelah tanggal akhir kontrak sebelumnya.")

	def before_submit(self):
		if not self.contract_file:
			frappe.throw("Lampirkan dokumen kontrak sebelum Submit.")
		# Serialize submissions for the same employee to prevent concurrent overlaps.
		frappe.db.sql("select name from `tabEmployee` where name=%s for update", self.employee)
		contracts = frappe.db.sql(
			"""select name, start_date, end_date, previous_contract
			from `tabEmployee Contract`
			where employee=%s and docstatus=1 and name!=%s for update""",
			(self.employee, self.name), as_dict=True,
		)
		for contract in contracts:
			if self.previous_contract and contract.previous_contract == self.previous_contract:
				frappe.throw("Kontrak sebelumnya sudah memiliki perpanjangan yang disubmit.")
			end = getdate(self.end_date) if self.end_date else getdate("9999-12-31")
			other_end = getdate(contract.end_date) if contract.end_date else getdate("9999-12-31")
			if getdate(self.start_date) <= other_end and getdate(contract.start_date) <= end:
				frappe.throw("Periode kontrak bertumpang tindih dengan {0}.".format(contract.name))


@frappe.whitelist()
def get_renewal_defaults(contract):
	previous = frappe.get_doc("Employee Contract", contract)
	previous.check_permission("read")
	if not frappe.has_permission("Employee Contract", "create"):
		frappe.throw("Anda tidak memiliki akses membuat kontrak.", frappe.PermissionError)
	if previous.docstatus != 1 or previous.contract_type != "PKWT" or not previous.end_date:
		frappe.throw("Perpanjangan hanya tersedia untuk kontrak PKWT yang sudah Submit.")
	return {
		"employee": previous.employee,
		"contract_type": "PKWT",
		"previous_contract": previous.name,
		"start_date": add_days(previous.end_date, 1),
	}
