"""Unit tests for toggleable, data-driven PPh 21 TER (PP 58/2023) calculations."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from custom_hr.services import pph21_ter as svc
from custom_hr.services.pph21_ter_defaults import (
	DEFAULT_EMPLOYER_BPJS,
	DEFAULT_PTKP_TER_MAP,
	DEFAULT_TER_RATES,
)


def make_settings(**overrides):
	base = {
		"enable_pph21_ter": 1,
		"pph21_ter_companies": "",
		"pph21_ptkp_map": [frappe._dict(r) for r in DEFAULT_PTKP_TER_MAP],
		"pph21_employer_bpjs": [frappe._dict(r) for r in DEFAULT_EMPLOYER_BPJS],
		"pph21_ter_rates": [frappe._dict(r) for r in DEFAULT_TER_RATES],
	}
	base.update(overrides)
	return frappe._dict(base)


def make_doc(**overrides):
	base = {
		"employee": "EMP-001",
		"company": "JURI",
		"marital_status": "Single",
		"dependents": "0",
		"earnings": [
			frappe._dict(salary_component="Gaji Pokok", amount=6000000, default_amount=6000000, is_tax_applicable=1),
		],
	}
	base.update(overrides)
	return frappe._dict(base)


class TestPPh21TER(unittest.TestCase):
	def test_toggle_off_returns_zero(self):
		settings = make_settings(enable_pph21_ter=0)
		res = svc.pph21_ter_values(make_doc(), settings=settings, dasar_bpjs=6000000)
		self.assertEqual(res, {"pph21_ter": 0.0, "dasar_bruto_pph21": 0.0, "tarif_ter_pph21": 0.0})

	def test_company_filter_limits_scope(self):
		settings = make_settings(
			pph21_ter_companies=[frappe._dict(company="JURI"), frappe._dict(company="Outlet A")]
		)
		self.assertGreater(
			svc.pph21_ter_values(make_doc(company="JURI"), settings=settings, dasar_bpjs=0)["pph21_ter"],
			0,
		)
		self.assertEqual(
			svc.pph21_ter_values(make_doc(company="Outlet B"), settings=settings, dasar_bpjs=0)["pph21_ter"],
			0.0,
		)
		# Empty table -> all companies apply
		all_co = make_settings(pph21_ter_companies=[])
		self.assertGreater(
			svc.pph21_ter_values(make_doc(company="Outlet B"), settings=all_co, dasar_bpjs=0)["pph21_ter"],
			0,
		)

	def test_ptkp_mapping_and_official_brackets(self):
		settings = make_settings()
		# Single/0 -> TK/0 -> TER A: 5.4M -> 0%; 6.0M -> 0.75% (5,950,001..6,300,000)
		below = svc.pph21_ter_values(
			make_doc(
				marital_status="Single",
				dependents="0",
				earnings=[frappe._dict(salary_component="Gaji Pokok", amount=5400000, is_tax_applicable=1)],
			),
			settings=settings,
			dasar_bpjs=0,
		)
		self.assertEqual(below, {"pph21_ter": 0.0, "dasar_bruto_pph21": 5400000.0, "tarif_ter_pph21": 0.0})

		above = svc.pph21_ter_values(
			make_doc(
				marital_status="Single",
				dependents="0",
				earnings=[frappe._dict(salary_component="Gaji Pokok", amount=6000000, is_tax_applicable=1)],
			),
			settings=settings,
			dasar_bpjs=0,
		)
		self.assertEqual(above, {"pph21_ter": 45000.0, "dasar_bruto_pph21": 6000000.0, "tarif_ter_pph21": 0.75})

		# Married/1 -> K/1 -> TER B: 6.0M <= 6.2M -> 0%; 7.0M -> 0.75% (6,850,001..7,300,000)
		k1_zero = svc.pph21_ter_values(
			make_doc(marital_status="Married", dependents="1"),
			settings=settings,
			dasar_bpjs=0,
		)
		self.assertEqual(k1_zero["tarif_ter_pph21"], 0.0)

		# Married/3 -> K/3 -> TER C: 10.0M -> 1.5% (9,800,001..10,950,000)
		k3 = svc.pph21_ter_values(
			make_doc(
				marital_status="Married",
				dependents="3",
				earnings=[frappe._dict(salary_component="Gaji Pokok", amount=10000000, is_tax_applicable=1)],
			),
			settings=settings,
			dasar_bpjs=0,
		)
		self.assertEqual(k3, {"pph21_ter": 150000.0, "dasar_bruto_pph21": 10000000.0, "tarif_ter_pph21": 1.5})

	def test_employer_bpjs_adds_to_bruto_with_cap_and_non_taxable_excluded(self):
		settings = make_settings()
		# dasar_bpjs = 20_000_000 -> JKK 0.24% (48,000) + JKM 0.30% (60,000) + Kes 4% capped 12M (480,000) = 588,000
		doc = make_doc(
			marital_status="Single",
			dependents="0",
			earnings=[
				frappe._dict(salary_component="Gaji Pokok", amount=6000000, is_tax_applicable=1),
				frappe._dict(salary_component="BPJS Pendapatan", amount=500000, is_tax_applicable=0),
				frappe._dict(salary_component="Statistik", amount=1000000, is_tax_applicable=1, statistical_component=1),
			],
		)
		flags = {"Gaji Pokok": 1, "BPJS Pendapatan": 0}
		with patch("frappe.get_cached_value", side_effect=lambda dt, name, field, **kw: flags.get(name) if dt == "Salary Component" else None):
			res = svc.pph21_ter_values(doc, settings=settings, dasar_bpjs=20000000)
		# bruto = 6,000,000 + 588,000 = 6,588,000 -> TER A 6,300,001..6,750,000 = 1.0% -> 65,880
		self.assertEqual(res["dasar_bruto_pph21"], 6588000.0)
		self.assertEqual(res["tarif_ter_pph21"], 1.0)
		self.assertEqual(res["pph21_ter"], 65880.0)

	def test_live_salary_component_flag_overrides_stale_detail_row(self):
		settings = make_settings(pph21_employer_bpjs=[])
		doc = make_doc(
			marital_status="Single",
			dependents="0",
			earnings=[
				# Stale Salary Detail has 0, while live Salary Component is 1
				frappe._dict(salary_component="Gaji Pokok", amount=6000000, is_tax_applicable=0),
			],
		)
		with patch("frappe.get_cached_value", side_effect=lambda dt, name, field, **kw: 1 if dt == "Salary Component" and name == "Gaji Pokok" else None):
			res = svc.pph21_ter_values(doc, settings=settings, dasar_bpjs=0)
		self.assertEqual(res, {"pph21_ter": 45000.0, "dasar_bruto_pph21": 6000000.0, "tarif_ter_pph21": 0.75})

	def test_custom_table_rates_take_effect_without_code_changes(self):
		# Verify zero hardcoding: modified Payroll Settings rows drive the calculation completely.
		custom_settings = make_settings(
			pph21_ptkp_map=[frappe._dict(marital_status="Single", dependents="0", ptkp_code="CUSTOM", ter_category="TER C")],
			pph21_employer_bpjs=[],
			pph21_ter_rates=[frappe._dict(ter_category="TER C", min_bruto=0, max_bruto=0, rate_percent=2.5)],
		)
		res = svc.pph21_ter_values(
			make_doc(
				marital_status="Single",
				dependents="0",
				earnings=[frappe._dict(salary_component="Gaji Pokok", amount=4000000, is_tax_applicable=1)],
			),
			settings=custom_settings,
			dasar_bpjs=4000000,
		)
		self.assertEqual(res, {"pph21_ter": 100000.0, "dasar_bruto_pph21": 4000000.0, "tarif_ter_pph21": 2.5})

	def test_decimal_bruto_between_integer_seams_never_drops_bracket(self):
		settings = make_settings(pph21_employer_bpjs=[])
		doc = make_doc(
			marital_status="Single",
			dependents="0",
			earnings=[frappe._dict(salary_component="Gaji Pokok", amount=5400000.60, is_tax_applicable=1)],
		)
		res = svc.pph21_ter_values(doc, settings=settings, dasar_bpjs=0)
		self.assertEqual(res["tarif_ter_pph21"], 0.25)

	def test_fetches_employee_ptkp_from_cached_doc_when_absent_on_slip(self):
		settings = make_settings(pph21_employer_bpjs=[])
		doc = frappe._dict(
			employee="EMP-002",
			company="JURI",
			earnings=[frappe._dict(salary_component="Gaji Pokok", amount=10000000, is_tax_applicable=1)],
		)
		def cached_val(dt, name, field, **kw):
			if dt == "Employee":
				return {"company": "JURI", "marital_status": "Married", "dependents": "3"}
			if dt == "Salary Component":
				return 1
			return None

		with patch("frappe.get_cached_value", side_effect=cached_val):
			res = svc.pph21_ter_values(doc, settings=settings, dasar_bpjs=0)
		self.assertEqual(res["tarif_ter_pph21"], 1.5)

	def test_validate_settings_rejects_invalid_tables(self):
		good = make_settings()
		svc.validate_settings(good)

		dup_ptkp = make_settings(
			pph21_ptkp_map=[
				frappe._dict(marital_status="Single", dependents="0", ptkp_code="TK/0", ter_category="TER A"),
				frappe._dict(marital_status="Single", dependents="0", ptkp_code="TK/0", ter_category="TER B"),
			]
		)
		with self.assertRaises(Exception):
			svc.validate_settings(dup_ptkp)

		overlap_rate = make_settings(
			pph21_ter_rates=[
				frappe._dict(ter_category="TER A", min_bruto=0, max_bruto=6000000, rate_percent=0),
				frappe._dict(ter_category="TER A", min_bruto=5500000, max_bruto=7000000, rate_percent=0.5),
			]
		)
		with self.assertRaises(Exception):
			svc.validate_settings(overlap_rate)

		empty_when_enabled = make_settings(pph21_ter_rates=[])
		with self.assertRaises(Exception):
			svc.validate_settings(empty_when_enabled)
