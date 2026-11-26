import frappe
from frappe.utils import flt
from hrms.payroll.doctype.salary_slip.salary_slip import SalarySlip, get_salary_component_data
from hrms.payroll.doctype.salary_structure_assignment.salary_structure_assignment import (
	SalaryStructureAssignment,
)

from custom_hr.services.payroll_penalties import bpjs_values, overtime_component_amounts
from custom_hr.services.pph21_ter import TER_FORMULA_KEYS, pph21_ter_values


class CustomSalarySlip(SalarySlip):
	"""BPJS, PPh 21 TER, and dynamic Overtime Type components join formula evaluation."""

	def add_structure_components(self, component_type):
		super().add_structure_components(component_type)
		if component_type == "earnings" and self.docstatus == 0:
			self.add_overtime_components()

	def add_overtime_components(self):
		"""Inject any Overtime Type earning component not already defined as a row in the Salary Structure."""
		struct_rows = (getattr(self, "_evaluated_components", None) or {}).get("earnings") or ()
		# Legacy structures route all overtime into one catch-all formula "upah_lembur".
		if any((getattr(row, "formula", "") or "").strip() == "upah_lembur" for row in struct_rows):
			return

		structured = {row.salary_component for row in struct_rows}
		amounts = overtime_component_amounts(self)
		overtime_linked = {c for c in frappe.get_all("Overtime Type", pluck="overtime_salary_component") if c}
		for comp in sorted((overtime_linked | set(amounts)) - structured):
			amount = flt(amounts.get(comp), 2)
			if amount > 0:
				if frappe.get_cached_value("Salary Component", comp, "type") != "Earning":
					continue
				component_data = frappe._dict(get_salary_component_data(comp) or {})
				if not component_data:
					continue
				component_data.depends_on_payment_days = 0
				component_data.deduct_full_tax_on_selected_payroll_date = 0
				self.update_component_row(
					component_data,
					amount,
					"earnings",
					data=self.data,
					default_amount=amount,
					remove_if_zero_valued=1,
				)
			else:
				# Drop stale dynamic overtime rows if Overtime Requests were cancelled before re-saving.
				self.set("earnings", [row for row in self.get("earnings") if not (row.salary_component == comp and not row.additional_salary)])

	def get_data_for_eval(self):
		data, default_data = super().get_data_for_eval()
		values = bpjs_values(self, self._salary_structure_assignment)
		self.dasar_bpjs = values["dasar_bpjs"]
		data.update(values)
		default_data.update(values)

		earnings = self.get("earnings")
		ter_data = pph21_ter_values(
			self,
			self._salary_structure_assignment,
			dasar_bpjs=values["dasar_bpjs"],
			earning_rows=earnings,
			amount_field="amount",
		)
		ter_default = pph21_ter_values(
			self,
			self._salary_structure_assignment,
			dasar_bpjs=values["dasar_bpjs"],
			earning_rows=earnings,
			amount_field="default_amount",
		)
		self.dasar_bruto_pph21 = ter_data["dasar_bruto_pph21"]
		self.tarif_ter_pph21 = ter_data["tarif_ter_pph21"]
		data.update(ter_data)
		default_data.update(ter_default)
		return data, default_data


class CustomSalaryStructureAssignment(SalaryStructureAssignment):
	"""The assignment evaluates the same formulas for its full-cycle amounts and CTC, so it needs the same names."""

	def _get_component_eval_context(self):
		data = super()._get_component_eval_context()
		data.update(bpjs_values(data, self.as_dict()))
		data.update({key: 0.0 for key in TER_FORMULA_KEYS})
		return data

	def _evaluate_component_table(self, rows, data):
		# Deductions evaluate right after earnings, when full-cycle taxable earnings are ready for TER lookup.
		if rows and getattr(rows[0], "parentfield", None) == "deductions":
			data.update(
				pph21_ter_values(
					data,
					self.as_dict(),
					dasar_bpjs=data.get("dasar_bpjs"),
					earning_rows=getattr(self, "_ter_eval_earnings", ()),
					amount_field="default_amount",
				)
			)
		evaluated = super()._evaluate_component_table(rows, data)
		if rows and getattr(rows[0], "parentfield", None) == "earnings":
			self._ter_eval_earnings = evaluated
		return evaluated
