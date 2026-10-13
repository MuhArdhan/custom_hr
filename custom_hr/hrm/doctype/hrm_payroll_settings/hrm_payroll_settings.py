# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class HRMPayrollSettings(Document):
	def validate(self):
		if flt(self.overtime_hourly_divisor) <= 0:
			frappe.throw(_("Pembagi upah sejam harus lebih dari 0"))
		if self.overtime_salary_component:
			component_type = frappe.db.get_value(
				"Salary Component", self.overtime_salary_component, "type"
			)
			if component_type != "Earning":
				frappe.throw(_("Komponen upah lembur harus bertipe Earning"))
