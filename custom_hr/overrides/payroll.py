from hrms.payroll.doctype.salary_slip.salary_slip import SalarySlip
from hrms.payroll.doctype.salary_structure_assignment.salary_structure_assignment import (
	SalaryStructureAssignment,
)

from custom_hr.services.payroll_penalties import bpjs_values


class CustomSalarySlip(SalarySlip):
	"""BPJS percentages live in Payroll Settings (tab HRM): their amounts join the formula variables, named by HR."""

	def get_data_for_eval(self):
		data, default_data = super().get_data_for_eval()
		values = bpjs_values(self, self._salary_structure_assignment)
		self.dasar_bpjs = values["dasar_bpjs"]
		data.update(values)
		default_data.update(values)
		return data, default_data


class CustomSalaryStructureAssignment(SalaryStructureAssignment):
	"""The assignment evaluates the same formulas for its full-cycle amounts and CTC, so it needs the same names."""

	def _get_component_eval_context(self):
		data = super()._get_component_eval_context()
		data.update(bpjs_values(data, self.as_dict()))
		return data
