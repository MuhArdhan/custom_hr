import frappe
from frappe import _
from frappe.utils import flt
from hrms.payroll.doctype.payroll_entry.payroll_entry import (
	PayrollEntry,
	get_filtered_employees,
	remove_payrolled_employees,
)
from hrms.payroll.doctype.salary_slip.salary_slip import SalarySlip, get_salary_component_data
from hrms.payroll.doctype.salary_structure_assignment.salary_structure_assignment import (
	SalaryStructureAssignment,
)

from custom_hr.services.payroll_penalties import bpjs_values, overtime_component_amounts
from custom_hr.services.pph21_ter import TER_FORMULA_KEYS, pph21_ter_values
from custom_hr.services.salary_structure_scope import (
	get_applicable_salary_structures,
	validate_assignment_scope,
)


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
	"""Allow lintas_company Salary Structures scoped by outlet/department, and keep BPJS/TER context."""

	def validate_company(self):
		validate_assignment_scope(self)

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


def get_employee_list_with_global_structures(
	filters: frappe._dict,
	searchfield=None,
	search_string=None,
	fields: list[str] | None = None,
	as_dict=True,
	limit=None,
	offset=None,
	ignore_match_conditions=False,
) -> list:
	sal_struct = get_applicable_salary_structures(
		filters.company,
		filters.currency,
		filters.salary_slip_based_on_timesheet,
		filters.payroll_frequency,
	)
	if not sal_struct:
		return []

	emp_list = get_filtered_employees(
		sal_struct,
		filters,
		searchfield,
		search_string,
		fields,
		as_dict=as_dict,
		limit=limit,
		offset=offset,
		ignore_match_conditions=ignore_match_conditions,
	)
	employees_to_check = {emp.employee: emp for emp in emp_list} if as_dict else {emp[0]: emp for emp in emp_list}
	return remove_payrolled_employees(employees_to_check, filters.start_date, filters.end_date)


class CustomPayrollEntry(PayrollEntry):
	"""Include global lintas_company Salary Structures when pulling employees for a Payroll Entry."""

	@frappe.whitelist()
	def fill_employee_details(self):
		filters = self.make_filters()
		employees = get_employee_list_with_global_structures(
			filters=filters, as_dict=True, ignore_match_conditions=True
		)
		self.set("employees", [])

		if not employees:
			error_msg = _(
				"No employees found for the mentioned criteria:<br>Company: {0}<br> Currency: {1}<br>Payroll Payable Account: {2}"
			).format(
				frappe.bold(self.company),
				frappe.bold(self.currency),
				frappe.bold(self.payroll_payable_account),
			)
			if self.branch:
				error_msg += "<br>" + _("Branch: {0}").format(frappe.bold(self.branch))
			if self.department:
				error_msg += "<br>" + _("Department: {0}").format(frappe.bold(self.department))
			if self.designation:
				error_msg += "<br>" + _("Designation: {0}").format(frappe.bold(self.designation))
			if self.start_date:
				error_msg += "<br>" + _("Start date: {0}").format(frappe.bold(self.start_date))
			if self.end_date:
				error_msg += "<br>" + _("End date: {0}").format(frappe.bold(self.end_date))
			frappe.throw(error_msg, title=_("No employees found"))

		self.set("employees", employees)
		self.number_of_employees = len(self.employees)
		self.update_employees_with_withheld_salaries()
		return self.get_employees_with_unmarked_attendance()


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def payroll_entry_employee_query(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict
) -> list:
	filters = frappe._dict(filters)
	if not filters.payroll_frequency:
		frappe.throw(_("Select Payroll Frequency."))

	employee_list = get_employee_list_with_global_structures(
		filters,
		searchfield=searchfield,
		search_string=txt,
		fields=["name", "employee_name"],
		as_dict=False,
		limit=page_len,
		offset=start,
	)
	return employee_list
