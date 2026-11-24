from hrms.payroll.doctype.salary_slip.salary_slip import SalarySlip
from hrms.payroll.doctype.salary_structure_assignment.salary_structure_assignment import (
	SalaryStructureAssignment,
)

from custom_hr.services.payroll_penalties import bpjs_values
from custom_hr.services.pph21_ter import TER_FORMULA_KEYS, pph21_ter_values


class CustomSalarySlip(SalarySlip):
	"""BPJS and PPh 21 TER variables join formula evaluation from Payroll Settings (tab HRM)."""

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
