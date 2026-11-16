"""Install-time setup that needs the app's fixtures to exist."""

import frappe

SETTINGS = "Payroll Settings"
FIELD = "overtime_salary_component"
COMPONENT = "Lembur"
# a single's custom field default is not written on its own: these are set once, when still empty
DEFAULTS = {
	"overtime_hourly_divisor": 173,
	"outlet_expense_account_number": "5120.001",
	"intercompany_receivable_account_number": "1132.003",
	"intercompany_payable_account_name": "Hutang Internal - JURI",
}


def set_default_overtime_component():
	"""after_sync runs after fixtures; init_singles() runs before them and cannot link to Lembur."""
	for field, value in DEFAULTS.items():
		if not frappe.db.get_single_value(SETTINGS, field):
			frappe.db.set_single_value(SETTINGS, field, value)
	if frappe.db.get_single_value(SETTINGS, FIELD) or not frappe.db.exists("Salary Component", COMPONENT):
		return
	frappe.db.set_single_value(SETTINGS, FIELD, COMPONENT)
