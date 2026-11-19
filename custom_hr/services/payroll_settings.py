"""The HRM tab of the native Payroll Settings: overtime basis, rates, BPJS and the salary sheet columns."""

import frappe
from frappe import _
from frappe.utils import flt

SETTINGS = "Payroll Settings"


def validate(doc, method=None):
	if flt(doc.overtime_hourly_divisor) <= 0:
		frappe.throw(_("Pembagi upah sejam harus lebih dari 0"))
	if doc.overtime_salary_component:
		component_type = frappe.db.get_value("Salary Component", doc.overtime_salary_component, "type")
		if component_type != "Earning":
			frappe.throw(_("Komponen upah lembur harus bertipe Earning"))
	companies = [row.for_company or "" for row in doc.attendance_penalty_rates]
	if len(companies) != len(set(companies)):
		frappe.throw(_("Tarif Potongan: satu company hanya boleh satu baris, dan hanya satu baris tanpa company."))
	places = [(row.for_company or "", row.for_department or "") for row in doc.daily_rates]
	if len(places) != len(set(places)):
		frappe.throw(_("Tarif Harian: satu company + department hanya boleh satu baris."))
	slip_fields = {df.fieldname for df in frappe.get_meta("Salary Slip").fields}
	codes = [(row.kode or "").strip() for row in doc.bpjs_rates]
	for code in codes:
		# the name becomes a formula variable: it must be one word and must not hide a slip field
		if not code.isidentifier() or code in slip_fields:
			frappe.throw(_("Iuran BPJS: Nama di Rumus {0} harus satu kata (huruf, angka, garis bawah) dan belum dipakai field Salary Slip.").format(code))
	if len(codes) != len(set(codes)):
		frappe.throw(_("Iuran BPJS: Nama di Rumus tidak boleh dobel."))
	from custom_hr.api.payroll_match import column_groups

	column_groups(doc.match_columns, set())  # refuses a column that is not letters
	shifts = [row.shift_type for row in doc.shift_allowances]
	if len(shifts) != len(set(shifts)):
		frappe.throw(_("Tunjangan Shift: satu Shift Type hanya boleh satu baris."))
	jobs = [row.designation for row in doc.designation_allowances]
	if len(jobs) != len(set(jobs)):
		frappe.throw(_("Tunjangan per Jabatan: satu jabatan hanya boleh satu baris."))
	places = [(row.salary_component, row.for_company or "") for row in doc.component_accounts]
	if len(places) != len(set(places)):
		frappe.throw(_("Akun Komponen Gaji: satu komponen hanya boleh satu baris per company, dan satu baris tanpa company."))
