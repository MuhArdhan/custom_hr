"""Apply attendance rules inside native payroll calculation, before totals."""

import json
from collections import defaultdict

import frappe
from frappe.utils import cint, flt, getdate, now_datetime

from custom_hr.api.payroll_attendance import collect_summary, snapshot_rows


def deduction_amounts(summary):
	amounts = {component: 0.0 for component in summary["managed_components"]}
	for row in summary["rows"]:
		if row["salary_component"] in amounts:
			amounts[row["salary_component"]] += flt(row["estimated_amount"])
	return {component: flt(amount, 2) for component, amount in amounts.items()}


def validate_deduction_amounts(doc, summary):
	for component, amount in deduction_amounts(summary).items():
		rows = [row for row in doc.get("deductions", []) if row.salary_component == component]
		if len(rows) != 1 or flt(rows[0].amount, 2) != amount or rows[0].get("additional_salary"):
			frappe.throw("Potongan presensi {0} tidak sesuai aturan. Hitung ulang Salary Slip.".format(component))


class AttendancePayrollMixin:
	def calculate_net_pay(self, *args, **kwargs):
		self._attendance_amounts = {}
		if self.docstatus == 1 and (getattr(self, "_action", None) != "submit"
			or frappe.db.get_value("Salary Slip", self.name, "docstatus") == 1):
			# Never refresh historical sources on a saved Submitted slip.
			for row in snapshot_rows(self):
				if row.get("managed_by_attendance"):
					component = row["salary_component"]
					self._attendance_amounts[component] = self._attendance_amounts.get(component, 0) + flt(row["estimated_amount"])
		elif self.docstatus != 2 and self.employee and self.start_date and self.end_date and self.salary_structure:
			summary = collect_summary(self.employee, self.start_date, self.end_date)
			self._attendance_amounts = deduction_amounts(summary)
			# Retired rules must not leave a previous automatic deduction on the Draft.
			previous = {row.get("salary_component") for row in snapshot_rows(self)
				if row.get("managed_by_attendance") or any(cint((source.get("rule") or {}).get("enabled"))
					for source in json.loads(row.get("source_details") or "[]"))}
			if previous - set(self._attendance_amounts):
				self.set("deductions", [row for row in self.deductions
					if row.salary_component not in previous - set(self._attendance_amounts)
					or row.get("additional_salary")])
			if self._attendance_amounts:
				self._validate_attendance_structure(summary)
				self.custom_hr_attendance_snapshot = json.dumps(summary["rows"], ensure_ascii=False)
				self.custom_hr_attendance_hash = summary["source_hash"]
				self.custom_hr_attendance_calculated_on = now_datetime()
				self.custom_hr_attendance_warnings = "\n".join(summary["warnings"] + summary["blockers"])
			elif previous:
				self.custom_hr_attendance_snapshot = None
				self.custom_hr_attendance_hash = None
				self.custom_hr_attendance_calculated_on = None
				self.custom_hr_attendance_warnings = None
		return super().calculate_net_pay(*args, **kwargs)

	def _validate_attendance_structure(self, summary):
		structure = frappe.get_cached_doc("Salary Structure", self.salary_structure)
		components = defaultdict(list)
		for row in structure.deductions:
			components[row.salary_component].append(row)
		for component in self._attendance_amounts:
			rows = components[component]
			if len(rows) != 1:
				frappe.throw("Tambahkan tepat satu komponen {0} pada Deduction Salary Structure.".format(component))
			row = rows[0]
			if any(row.get(field) for field in ("amount_based_on_formula", "formula", "condition",
				"depends_on_payment_days", "statistical_component", "variable_based_on_taxable_salary",
				"do_not_include_in_total", "accrual_component")) or flt(row.amount):
				frappe.throw("Komponen {0} dikelola aturan presensi: kosongkan formula/kondisi/nominal, "
					"nonaktifkan Depends on Payment Days dan flag statistik/pajak/accrual.".format(component))
			for detail in self.get("deductions", []):
				if detail.salary_component == component and detail.get("additional_salary"):
					frappe.throw("Komponen {0} sudah berasal dari Additional Salary; tidak boleh dipotong ganda.".format(component))
				if detail.salary_component == component and any(detail.get(field) for field in (
					"depends_on_payment_days", "do_not_include_in_total")):
					frappe.throw("Flag komponen {0} pada slip bertentangan dengan potongan presensi.".format(component))
			if frappe.db.exists("Additional Salary", {"employee": self.employee, "salary_component": component,
				"docstatus": 1, "is_recurring": 0, "payroll_date": ["between", [self.start_date, self.end_date]]}):
				frappe.throw("Additional Salary {0} sudah ada pada periode ini; selesaikan konflik potongan.".format(component))
			for extra in frappe.get_all("Additional Salary", filters={"employee": self.employee,
				"salary_component": component, "docstatus": 1, "is_recurring": 1}, fields=["from_date", "to_date"]):
				if (getdate(extra.from_date or "0001-01-01") <= getdate(self.end_date)
					and getdate(extra.to_date or "9999-12-31") >= getdate(self.start_date)):
					frappe.throw("Additional Salary berulang {0} bertumpang tindih dengan potongan presensi.".format(component))
			if sum(row.salary_component == component for row in self.get("deductions", [])) > 1:
				frappe.throw("Komponen potongan {0} duplikat pada slip.".format(component))
		# Native LWP/payment-days deductions remain authoritative, not a second charge.
		for row in summary["rows"]:
			if row["salary_component"] not in self._attendance_amounts or not row["quantity"]:
				continue
			if any(source.get("native_handled") and cint((source.get("rule") or {}).get("enabled"))
				for source in json.loads(row["source_details"])):
				frappe.throw("{0} sudah ditangani native LWP/payment days. Nonaktifkan estimasi otomatis "
					"kategori ini agar tidak terjadi potongan ganda.".format(row["category"]))

	def add_structure_component(self, struct_row, component_type):
		amounts = getattr(self, "_attendance_amounts", {})
		if component_type != "deductions" or struct_row.salary_component not in amounts:
			return super().add_structure_component(struct_row, component_type)
		if any(struct_row.get(field) for field in ("amount_based_on_formula", "formula", "condition",
			"depends_on_payment_days", "statistical_component", "variable_based_on_taxable_salary",
			"do_not_include_in_total", "accrual_component")):
			frappe.throw("Konfigurasi komponen {0} pada SSA bertentangan dengan aturan presensi.".format(struct_row.salary_component))
		amount = amounts[struct_row.salary_component]
		self.update_component_row(struct_row, amount, component_type, data=self.data,
			default_amount=amount, remove_if_zero_valued=False)
		self.data[struct_row.abbr] = amount
		self.default_data[struct_row.abbr] = amount
