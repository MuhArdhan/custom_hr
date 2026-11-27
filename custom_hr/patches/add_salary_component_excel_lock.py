"""Lock Kasbon and dedicated Overtime components from accidental Cocokkan Gaji Excel overrides."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def execute():
	if not frappe.db.exists("Custom Field", "Salary Component-disallow_excel_override"):
		create_custom_field(
			"Salary Component",
			{
				"fieldname": "disallow_excel_override",
				"fieldtype": "Check",
				"label": "Kunci dari Pakai Excel (Cocokkan Gaji)",
				"description": "Jika dicentang, komponen ini tidak bisa ditimpa langsung dari tombol Excel di Cocokkan Gaji (mis. Kasbon atau Lembur otomatis).",
				"insert_after": "show_in_period_input",
				"module": "HRM",
				"default": "0",
			},
		)
	if not frappe.db.has_column("Salary Component", "disallow_excel_override"):
		return

	locked = {"Kasbon", "Lembur", "Lembur Reguler", "Lembur Holiday"}
	locked.update(
		c
		for c in frappe.get_all(
			"Overtime Type",
			filters={"disabled": 0, "name": ["!=", "Regular"]},
			pluck="overtime_salary_component",
		)
		if c
	)
	for name in sorted(locked):
		if frappe.db.exists("Salary Component", name):
			frappe.db.set_value("Salary Component", name, "disallow_excel_override", 1, update_modified=False)
