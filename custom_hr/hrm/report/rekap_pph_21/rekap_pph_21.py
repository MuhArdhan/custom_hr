"""Laporan Rekap PPh 21 TER (PP 58/2023) mengikuti struktur sheet PPH21 (kolom A sampai AH)."""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from custom_hr.api.payroll_match import nip_text
from custom_hr.services.pph21_ter import (
	employer_bpjs_breakdown,
	is_pph21_ter_enabled,
	is_taxable_earning,
	ptkp_info_for,
	ter_rate_for,
)

MONTH_NAMES_ID = (
	"",
	"Januari",
	"Februari",
	"Maret",
	"April",
	"Mei",
	"Juni",
	"Juli",
	"Agustus",
	"September",
	"Oktober",
	"November",
	"Desember",
)

PREFERRED_EARNING_ORDER = (
	"Gaji Pokok",
	"Gaji Harian",
	"Basic",
	"Uang Makan",
	"Tunjangan Transport",
	"Tunjangan Jabatan",
	"Resiko",
	"Tunjangan Tempat Tinggal",
	"Tunjangan Shift",
	"Tunjangan Harian",
	"Tunjangan Tetap",
	"Upah Lembur",
	"Lembur",
	"Lembur Driver",
	"Lembur Reguler",
	"Lembur Holiday",
	"Bonus Performance",
	"Bonus Target",
	"Insentif",
	"Training",
	"Vending Mesin",
	"Arrear",
	"Leave Encashment",
)

GENDER_SHORT = {"Male": "L", "Female": "P"}


def _slug(prefix: str, label: str, used: set[str]) -> str:
	base = f"{prefix}_{re.sub(r'[^a-z0-9]+', '_', (label or '').lower()).strip('_') or 'item'}"
	key = base
	idx = 2
	while key in used:
		key = f"{base}_{idx}"
		idx += 1
	used.add(key)
	return key


def _query_slips(filters: dict) -> list:
	conditions = ["ss.docstatus < 2"] if cint(filters.get("include_draft", 1)) else ["ss.docstatus = 1"]
	params = []

	if filters.get("payroll_entry"):
		conditions.append("ss.payroll_entry = %s")
		params.append(filters["payroll_entry"])
	else:
		if filters.get("from_date"):
			conditions.append("ss.end_date >= %s")
			params.append(filters["from_date"])
		if filters.get("to_date"):
			conditions.append("ss.end_date <= %s")
			params.append(filters["to_date"])

	if filters.get("company"):
		conditions.append("ss.company = %s")
		params.append(filters["company"])

	where = " AND ".join(conditions)
	return frappe.db.sql(
		f"""
		SELECT
			ss.name, ss.employee, ss.employee_name, ss.company, ss.department, ss.designation,
			ss.start_date, ss.end_date, ss.docstatus,
			ss.dasar_bpjs, ss.dasar_bruto_pph21, ss.tarif_ter_pph21,
			emp.employee_number AS nip, emp.nik, emp.gender,
			emp.marital_status, emp.dependents
		FROM `tabSalary Slip` ss
		JOIN `tabEmployee` emp ON emp.name = ss.employee
		WHERE {where}
		ORDER BY ss.end_date DESC, ss.company, ss.employee_name
		""",
		params,
		as_dict=True,
	)


def _fetch_details(slip_names: list[str], taxable_map: dict[str, int]):
	earnings_by_slip: dict[str, dict[str, float]] = {}
	pph21_by_slip: dict[str, float] = {}
	active_earnings: set[str] = set()

	if not slip_names:
		return earnings_by_slip, pph21_by_slip, []

	details = frappe.get_all(
		"Salary Detail",
		filters={"parenttype": "Salary Slip", "parent": ["in", slip_names]},
		fields=[
			"parent",
			"parentfield",
			"salary_component",
			"amount",
			"is_tax_applicable",
			"statistical_component",
		],
	)
	for row in details:
		if row.parentfield == "earnings":
			if not is_taxable_earning(row, taxable_map=taxable_map):
				continue
			amt = flt(row.amount)
			slip_map = earnings_by_slip.setdefault(row.parent, {})
			slip_map[row.salary_component] = slip_map.get(row.salary_component, 0.0) + amt
			if amt:
				active_earnings.add(row.salary_component)
		elif row.parentfield == "deductions" and row.salary_component == "PPh 21":
			pph21_by_slip[row.parent] = pph21_by_slip.get(row.parent, 0.0) + flt(row.amount)

	rank = {name: i for i, name in enumerate(PREFERRED_EARNING_ORDER)}
	ordered = sorted(active_earnings, key=lambda n: (rank.get(n, len(PREFERRED_EARNING_ORDER)), n))
	return earnings_by_slip, pph21_by_slip, ordered


def build_report(slips, details_by_slip, pph21_by_slip, ordered_earnings, settings, simulate: bool = False):
	used_keys: set[str] = set()
	earning_cols = [(name, _slug("earn", name, used_keys)) for name in ordered_earnings]
	bpjs_codes = [(row.get("kode") if hasattr(row, "get") else getattr(row, "kode", "")) for row in (settings.get("pph21_employer_bpjs") or [])]
	bpjs_cols = [(code, _slug("bpjs", code, used_keys)) for code in bpjs_codes if code]

	ptkp_map = settings.get("pph21_ptkp_map") or []
	employer_rows = settings.get("pph21_employer_bpjs") or []
	ter_rates = settings.get("pph21_ter_rates") or []

	money = {"fieldtype": "Currency", "options": "currency", "width": 125}
	cols = [
		{"fieldname": "bulan", "label": _("Bulan"), "fieldtype": "Data", "width": 95},
		{"fieldname": "nik", "label": _("NIK"), "fieldtype": "Data", "width": 145},
		{"fieldname": "nip", "label": _("NIP"), "fieldtype": "Data", "width": 95},
		{"fieldname": "employee", "label": _("Employee"), "fieldtype": "Link", "options": "Employee", "width": 125},
		{"fieldname": "employee_name", "label": _("Nama"), "fieldtype": "Data", "width": 180},
		{"fieldname": "company", "label": _("Company"), "fieldtype": "Link", "options": "Company", "width": 170},
		{"fieldname": "department", "label": _("Departemen"), "fieldtype": "Data", "width": 135},
		{"fieldname": "designation", "label": _("Jabatan"), "fieldtype": "Data", "width": 130},
		{"fieldname": "gender", "label": _("JK"), "fieldtype": "Data", "width": 55},
		{"fieldname": "ptkp", "label": _("PTKP"), "fieldtype": "Data", "width": 70},
		*[dict(money, fieldname=key, label=_(name)) for name, key in earning_cols],
		*[dict(money, fieldname=key, label=_("BPJS: {0}").format(code)) for code, key in bpjs_cols],
		dict(money, fieldname="total_bpjs_perusahaan", label=_("Total BPJS Perusahaan")),
		dict(money, fieldname="bruto_pph21", label=_("Total Penghasilan Bruto")),
		{"fieldname": "ter_category", "label": _("Kategori TER"), "fieldtype": "Data", "width": 95},
		{"fieldname": "tarif_ter", "label": _("Tarif TER (%)"), "fieldtype": "Float", "precision": 4, "width": 95},
		dict(money, fieldname="pph21", label=_("PPh 21")),
	]

	rows = []
	for slip in slips:
		end_dt = getdate(slip.end_date) if slip.end_date else None
		month_num = end_dt.month if end_dt else 0
		ptkp_code, ter_cat = ptkp_info_for(ptkp_map, slip.marital_status, slip.dependents)

		earned = details_by_slip.get(slip.name, {})
		taxable_sum = flt(sum(earned.values()), 2)

		bpjs_items = employer_bpjs_breakdown(employer_rows, flt(slip.dasar_bpjs))
		bpjs_by_code = {k: amt for k, amt in bpjs_items if k}
		total_emp_bpjs = flt(sum(amt for _k, amt in bpjs_items), 2)
		computed_bruto = flt(taxable_sum + total_emp_bpjs, 2) if taxable_sum > 0 else 0.0

		if simulate:
			bruto = computed_bruto
			rate_pct = ter_rate_for(ter_rates, ter_cat, bruto)
			pph21_amt = flt(bruto * rate_pct / 100.0, 2)
		else:
			recorded_tax = flt(pph21_by_slip.get(slip.name))
			enabled = is_pph21_ter_enabled(settings, slip.company)
			bruto = flt(slip.dasar_bruto_pph21) if flt(slip.dasar_bruto_pph21) > 0 else computed_bruto
			rate_pct = flt(slip.tarif_ter_pph21) if (enabled or recorded_tax > 0) else 0.0
			pph21_amt = recorded_tax

		nik_val = (slip.nik or "").strip()
		row = {
			"currency": "IDR",
			"bulan": MONTH_NAMES_ID[month_num] if 1 <= month_num <= 12 else "",
			"nik": nik_val,
			"nip": nip_text(slip.nip),
			"employee": slip.employee,
			"employee_name": slip.employee_name,
			"company": slip.company,
			"department": slip.department,
			"designation": slip.designation,
			"gender": GENDER_SHORT.get(slip.gender, slip.gender or ""),
			"ptkp": ptkp_code or "",
			"total_bpjs_perusahaan": total_emp_bpjs,
			"bruto_pph21": bruto,
			"ter_category": ter_cat or "",
			"tarif_ter": rate_pct,
			"pph21": pph21_amt,
		}
		for comp_name, key in earning_cols:
			row[key] = flt(earned.get(comp_name), 2)
		for code, key in bpjs_cols:
			row[key] = flt(bpjs_by_code.get(code), 2)
		rows.append(row)

	return cols, rows


def execute(filters=None):
	filters = filters or {}
	frappe.has_permission("Salary Slip", "read", throw=True)
	if filters.get("payroll_entry"):
		frappe.has_permission("Payroll Entry", "read", filters["payroll_entry"], throw=True)

	settings = frappe.get_cached_doc("Payroll Settings", "Payroll Settings")
	slips = _query_slips(filters)
	taxable_map = {
		c.name: cint(c.is_tax_applicable)
		for c in frappe.get_all("Salary Component", fields=["name", "is_tax_applicable"])
	}
	details_by_slip, pph21_by_slip, ordered_earnings = _fetch_details([s.name for s in slips], taxable_map)
	return build_report(
		slips,
		details_by_slip,
		pph21_by_slip,
		ordered_earnings,
		settings,
		simulate=bool(cint(filters.get("simulasi_ter"))),
	)
