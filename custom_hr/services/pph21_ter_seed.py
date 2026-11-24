"""Idempotent seeder for PPh 21 TER Payroll Settings tables and Salary Component."""

from __future__ import annotations

import frappe

from custom_hr.services.pph21_ter_defaults import (
	DEFAULT_EMPLOYER_BPJS,
	DEFAULT_PTKP_TER_MAP,
	DEFAULT_TER_RATES,
)


def seed_defaults() -> None:
	"""Populate empty PPh 21 TER tables on Payroll Settings and ensure PPh 21 component exists.

	Safe to re-run: existing HR edits and the enable/disable toggle are preserved.
	"""
	if frappe.db.exists("DocType", "HRM PTKP TER Map") and frappe.db.exists("DocType", "HRM TER Rate"):
		settings = frappe.get_single("Payroll Settings")
		dirty = False

		if not settings.get("pph21_ptkp_map"):
			for row in DEFAULT_PTKP_TER_MAP:
				settings.append("pph21_ptkp_map", dict(row))
			dirty = True

		if not settings.get("pph21_employer_bpjs"):
			for row in DEFAULT_EMPLOYER_BPJS:
				settings.append("pph21_employer_bpjs", dict(row))
			dirty = True

		if not settings.get("pph21_ter_rates"):
			for row in DEFAULT_TER_RATES:
				settings.append("pph21_ter_rates", dict(row))
			dirty = True

		if dirty:
			settings.flags.ignore_permissions = True
			settings.save()

	if not frappe.db.exists("Salary Component", "PPh 21"):
		doc = frappe.get_doc(
			{
				"doctype": "Salary Component",
				"salary_component": "PPh 21",
				"salary_component_abbr": "pph21",
				"type": "Deduction",
				"description": "Potongan PPh Pasal 21 metode Tarif Efektif Rata-Rata (TER PP 58/2023).",
				"amount_based_on_formula": 1,
				"formula": "pph21_ter",
				"depends_on_payment_days": 0,
				"remove_if_zero_valued": 1,
				"variable_based_on_taxable_salary": 0,
				"is_income_tax_component": 0,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert(ignore_if_duplicate=True)
