"""Data-driven PPh 21 TER (PP 58/2023) calculation and Payroll Settings validation.

All PTKP mappings, TER bracket rates, employer BPJS bruto additions, and the
master enable toggle live in Payroll Settings so HR can adjust rules without
code changes.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt

TER_FORMULA_KEYS = ("pph21_ter", "dasar_bruto_pph21", "tarif_ter_pph21")


def _zero_values() -> dict[str, float]:
	return {key: 0.0 for key in TER_FORMULA_KEYS}


def _row_value(row, key, default=None):
	return row.get(key, default) if hasattr(row, "get") else getattr(row, key, default)


def parse_company_filter(raw_companies) -> set[str]:
	"""Return configured company names, or an empty set when all companies apply."""
	if not raw_companies:
		return set()
	if isinstance(raw_companies, str):
		return {line.strip() for line in raw_companies.splitlines() if line.strip()}
	companies: set[str] = set()
	for row in raw_companies:
		val = row if isinstance(row, str) else _row_value(row, "company")
		if val and str(val).strip():
			companies.add(str(val).strip())
	return companies


def is_pph21_ter_enabled(settings, company: str | None = None) -> bool:
	"""Return True only when the toggle is ON and the slip company is in scope."""
	if not cint(_row_value(settings, "enable_pph21_ter", 0)):
		return False
	allowed = parse_company_filter(_row_value(settings, "pph21_ter_companies"))
	if not allowed:
		return True
	return bool(company and company in allowed)


def _normalize_dependents(value) -> str:
	if value is None or str(value).strip() == "":
		return "0"
	return str(cint(value))


def ptkp_info_for(ptkp_map, marital_status: str | None, dependents=None) -> tuple[str | None, str | None]:
	"""Resolve (ptkp_code, ter_category) via Payroll Settings PTKP mapping."""
	status = (marital_status or "").strip()
	dep = _normalize_dependents(dependents)

	for row in ptkp_map or ():
		row_status = (_row_value(row, "marital_status") or "").strip()
		row_dep = _normalize_dependents(_row_value(row, "dependents"))
		if row_status == status and row_dep == dep:
			return _row_value(row, "ptkp_code"), _row_value(row, "ter_category")

	# Fallback to Single when Employee.marital_status has not been filled in yet.
	if not status:
		for candidate_dep in (dep, "0"):
			for row in ptkp_map or ():
				if (_row_value(row, "marital_status") or "").strip() == "Single" and _normalize_dependents(
					_row_value(row, "dependents")
				) == candidate_dep:
					return _row_value(row, "ptkp_code"), _row_value(row, "ter_category")
	return None, None


def ter_category_for(ptkp_map, marital_status: str | None, dependents=None) -> str | None:
	"""Resolve (marital_status, dependents) via Payroll Settings PTKP mapping."""
	return ptkp_info_for(ptkp_map, marital_status, dependents)[1]


def employer_bpjs_breakdown(employer_bpjs_rows, dasar_bpjs: float) -> list[tuple[str, float]]:
	"""Compute each configured employer BPJS contribution added to PPh 21 bruto."""
	base = flt(dasar_bpjs)
	if base <= 0:
		return [(_row_value(row, "kode") or "", 0.0) for row in (employer_bpjs_rows or ())]

	items: list[tuple[str, float]] = []
	for row in employer_bpjs_rows or ():
		kode = (_row_value(row, "kode") or "").strip()
		rate_pct = flt(_row_value(row, "persen"))
		if rate_pct <= 0:
			items.append((kode, 0.0))
			continue
		cap = flt(_row_value(row, "batas_atas"))
		capped_base = min(base, cap) if cap > 0 else base
		items.append((kode, flt(capped_base * rate_pct / 100.0, 2)))
	return items


def employer_bpjs_amount(employer_bpjs_rows, dasar_bpjs: float) -> float:
	"""Compute total employer BPJS contributions added to PPh 21 bruto."""
	return flt(sum(amt for _kode, amt in employer_bpjs_breakdown(employer_bpjs_rows, dasar_bpjs)), 2)


def is_taxable_earning(row, taxable_map: dict[str, int] | None = None) -> bool:
	"""Return True when an earning row is subject to PPh 21 based on live Salary Component settings."""
	if cint(_row_value(row, "statistical_component", 0)):
		return False
	comp = _row_value(row, "salary_component")
	if comp:
		if taxable_map is not None and comp in taxable_map:
			return cint(taxable_map[comp]) == 1
		# Read live flag on Salary Component so HR doesn't need to re-save hundreds of Salary Structures.
		comp_flag = frappe.get_cached_value("Salary Component", comp, "is_tax_applicable")
		if comp_flag is not None:
			return cint(comp_flag) == 1
	flag = _row_value(row, "is_tax_applicable")
	return True if flag is None else cint(flag) == 1


def taxable_earnings_total(earning_rows, amount_field: str = "amount") -> float:
	"""Sum taxable earnings using the requested amount column (amount or default_amount)."""
	total = 0.0
	for row in earning_rows or ():
		if is_taxable_earning(row):
			total += flt(_row_value(row, amount_field, 0))
	return flt(total, 2)


def ter_rate_for(ter_rates, ter_category: str | None, bruto: float) -> float:
	"""Look up the effective TER percentage for a category and monthly bruto."""
	if not ter_category or flt(bruto) <= 0:
		return 0.0

	# Integer rupiah matching avoids 1-rupiah gaps (e.g. 5,400,000 -> 5,400,001) caused by BPJS decimals.
	lookup_bruto = round(flt(bruto))
	rows = sorted(
		(r for r in (ter_rates or ()) if _row_value(r, "ter_category") == ter_category),
		key=lambda r: flt(_row_value(r, "min_bruto")),
	)
	for row in rows:
		lo = flt(_row_value(row, "min_bruto"))
		hi = flt(_row_value(row, "max_bruto"))
		if lookup_bruto >= lo and (hi <= 0 or lookup_bruto <= hi):
			return flt(_row_value(row, "rate_percent"))
	return 0.0


def _employee_tax_profile(doc, ssa) -> tuple[str | None, str | None, str | None]:
	employee = _row_value(doc, "employee") or _row_value(ssa, "employee")
	company = _row_value(doc, "company") or _row_value(ssa, "company")
	marital_status = _row_value(doc, "marital_status")
	dependents = _row_value(doc, "dependents")

	if employee and (company is None or marital_status is None or dependents is None):
		emp_info = (
			frappe.get_cached_value(
				"Employee",
				employee,
				["company", "marital_status", "dependents"],
				as_dict=True,
			)
			or {}
		)
		if company is None:
			company = emp_info.get("company")
		if marital_status is None:
			marital_status = emp_info.get("marital_status")
		if dependents is None:
			dependents = emp_info.get("dependents")

	return company, marital_status, dependents


def pph21_ter_values(
	doc,
	ssa=None,
	*,
	settings=None,
	dasar_bpjs: float | None = None,
	earning_rows=None,
	amount_field: str = "amount",
) -> dict[str, float]:
	"""Return pph21_ter, dasar_bruto_pph21, and tarif_ter_pph21 for formula evaluation."""
	if settings is None:
		settings = frappe.get_cached_doc("Payroll Settings", "Payroll Settings")

	company, marital_status, dependents = _employee_tax_profile(doc, ssa)
	if not is_pph21_ter_enabled(settings, company):
		return _zero_values()

	rows = earning_rows if earning_rows is not None else (_row_value(doc, "earnings") or ())
	if not rows:
		return _zero_values()

	if dasar_bpjs is None:
		from custom_hr.services.payroll_penalties import bpjs_values

		dasar_bpjs = bpjs_values(doc, ssa)["dasar_bpjs"]

	taxable = taxable_earnings_total(rows, amount_field=amount_field)
	emp_bpjs = employer_bpjs_amount(_row_value(settings, "pph21_employer_bpjs"), dasar_bpjs)
	bruto = flt(taxable + emp_bpjs, 2)
	if bruto <= 0:
		return _zero_values()

	ter_cat = ter_category_for(_row_value(settings, "pph21_ptkp_map"), marital_status, dependents)
	rate_pct = ter_rate_for(_row_value(settings, "pph21_ter_rates"), ter_cat, bruto)
	tax = flt(bruto * rate_pct / 100.0, 2)
	return {
		"pph21_ter": tax,
		"dasar_bruto_pph21": bruto,
		"tarif_ter_pph21": rate_pct,
	}


def _validate_ptkp_map(doc) -> None:
	seen: set[tuple[str, str]] = set()
	for idx, row in enumerate(doc.get("pph21_ptkp_map") or [], start=1):
		key = ((row.marital_status or "").strip(), _normalize_dependents(row.dependents))
		if key in seen:
			frappe.throw(
				f"Mapping PTKP baris {idx} ({key[0]}, tanggungan {key[1]}) duplikat."
			)
		seen.add(key)


def _validate_employer_bpjs(doc) -> None:
	seen: set[str] = set()
	for idx, row in enumerate(doc.get("pph21_employer_bpjs") or [], start=1):
		code = (row.kode or "").strip().lower()
		if not code:
			frappe.throw(f"BPJS Perusahaan baris {idx}: kolom Komponen wajib diisi.")
		if code in seen:
			frappe.throw(f"BPJS Perusahaan baris {idx} ({row.kode}) duplikat.")
		seen.add(code)
		if flt(row.persen) < 0 or flt(row.batas_atas) < 0:
			frappe.throw(f"BPJS Perusahaan baris {idx} ({row.kode}): persen dan batas atas tidak boleh negatif.")


def _validate_ter_rates(doc) -> None:
	by_cat: dict[str, list[tuple[int, float, float]]] = {}
	for idx, row in enumerate(doc.get("pph21_ter_rates") or [], start=1):
		lo = flt(row.min_bruto)
		hi = flt(row.max_bruto)
		rate = flt(row.rate_percent)
		if lo < 0 or hi < 0 or rate < 0:
			frappe.throw(f"Tabel Tarif TER baris {idx}: nilai bruto dan tarif tidak boleh negatif.")
		if hi > 0 and hi < lo:
			frappe.throw(
				f"Tabel Tarif TER baris {idx} ({row.ter_category}): Bruto Maksimum ({hi:g}) "
				f"lebih kecil dari Bruto Minimum ({lo:g})."
			)
		by_cat.setdefault(row.ter_category or "", []).append((idx, lo, hi))

	for cat, brackets in by_cat.items():
		brackets.sort(key=lambda item: (item[1], item[2] if item[2] > 0 else float("inf")))
		for i in range(len(brackets) - 1):
			idx_a, _lo_a, hi_a = brackets[i]
			idx_b, lo_b, _hi_b = brackets[i + 1]
			if hi_a <= 0:
				frappe.throw(
					f"Tabel Tarif TER {cat} baris {idx_a}: lapisan tanpa batas atas (0) harus menjadi lapisan terakhir."
				)
			if lo_b <= hi_a:
				frappe.throw(
					f"Tabel Tarif TER {cat} baris {idx_a} dan {idx_b} tumpang tindih ({lo_b:g} <= {hi_a:g})."
				)


def validate_settings(doc, method=None) -> None:
	"""Validate PPh 21 TER configuration tables on Payroll Settings."""
	_validate_ptkp_map(doc)
	_validate_employer_bpjs(doc)
	_validate_ter_rates(doc)

	if cint(doc.get("enable_pph21_ter")):
		if not (doc.get("pph21_ptkp_map") or []):
			frappe.throw("Mapping PTKP ke Kategori TER wajib diisi sebelum mengaktifkan PPh 21 TER.")
		if not (doc.get("pph21_ter_rates") or []):
			frappe.throw("Tabel Tarif PPh 21 TER wajib diisi sebelum mengaktifkan PPh 21 TER.")
