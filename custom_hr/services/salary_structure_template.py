"""Master template replication and sync for per-company Salary Structures."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint

SCALAR_FIELDS = (
	"payroll_frequency",
	"salary_slip_based_on_timesheet",
	"salary_component",
	"hour_rate",
	"max_benefits",
	"leave_encashment_amount_per_day",
	"letter_head",
)
DETAIL_TABLES = ("earnings", "deductions", "employer_contributions", "employee_benefits")
ROW_META_KEYS = {
	"name",
	"owner",
	"creation",
	"modified",
	"modified_by",
	"parent",
	"parentfield",
	"parenttype",
	"idx",
	"docstatus",
}


def resolve_prefix(doc) -> str:
	"""Prefix used before ' - <Company>' for replicated structures."""
	explicit = (doc.get("template_prefix") or "").strip()
	if explicit:
		return explicit
	name = (doc.get("name") or "").strip()
	return name.split(" - ", 1)[0].strip() if " - " in name else name


def target_structure_name(prefix: str, company: str) -> str:
	return f"{prefix} - {company}"


def _clean_row(row) -> dict:
	data = row.as_dict() if callable(getattr(row, "as_dict", None)) else dict(row)
	return {k: v for k, v in data.items() if k not in ROW_META_KEYS}


def _copy_structure_content(source, target, company: str | None = None) -> None:
	for fieldname in SCALAR_FIELDS:
		target.set(fieldname, source.get(fieldname))
	if company:
		target.currency = source.get("currency") or frappe.db.get_value("Company", company, "default_currency") or "IDR"
	elif source.get("currency"):
		target.currency = source.get("currency")
	for table in DETAIL_TABLES:
		target.set(table, [])
		for row in source.get(table) or []:
			target.append(table, _clean_row(row))


def validate_template(doc, method=None) -> None:
	"""Salary Structure validate / on_update_after_submit: prevent duplicate active master prefixes."""
	if not cint(doc.get("is_master_template")) or doc.get("docstatus") == 2 or doc.get("is_active") == "No":
		return
	prefix = resolve_prefix(doc)
	if not prefix:
		frappe.throw(_("Awalan Nama per Company wajib diisi untuk Template Master."))
	others = frappe.get_all(
		"Salary Structure",
		filters={"is_master_template": 1, "docstatus": ["<", 2], "is_active": "Yes", "name": ["!=", doc.name or ""]},
		fields=["name", "template_prefix"],
	)
	for other in others:
		if resolve_prefix(other) == prefix:
			frappe.throw(
				_("Sudah ada Template Master aktif dengan awalan '{0}' ({1}). Lepas centang Template Master di struktur tersebut dulu.").format(
					prefix, other.name
				)
			)


def replicate_to_company(template_doc, company: str) -> str | None:
	"""Create & submit <prefix> - <Company> from template_doc if missing. Returns created name or None."""
	prefix = resolve_prefix(template_doc)
	dest_name = target_structure_name(prefix, company)
	if frappe.db.exists("Salary Structure", dest_name):
		return None
	doc = frappe.new_doc("Salary Structure")
	doc.__newname = dest_name
	doc.name = dest_name
	doc.company = company
	doc.is_active = "Yes"
	doc.is_default = template_doc.get("is_default") or "No"
	doc.is_master_template = 0
	doc.template_prefix = None
	doc.source_template = template_doc.name
	_copy_structure_content(template_doc, doc, company=company)
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def sync_existing_child(template_doc, target_name: str) -> bool:
	"""Update an existing submitted child Salary Structure's components/formulas from template_doc."""
	target = frappe.get_doc("Salary Structure", target_name)
	if cint(target.get("is_master_template")) or target.docstatus != 1 or target.is_active != "Yes":
		return False
	_copy_structure_content(template_doc, target)
	target.source_template = template_doc.name
	target.flags.ignore_validate_update_after_submit = True
	target.set_missing_values()
	target.validate_formula_setup()
	target.save(ignore_permissions=True)
	return True


def on_outlet_insert(doc, method=None) -> None:
	"""Outlet after_insert: automatically create active Salary Structures from every master template."""
	if not frappe.db.exists("Company", doc.name):
		return
	masters = frappe.get_all(
		"Salary Structure",
		filters={"is_master_template": 1, "docstatus": 1, "is_active": "Yes"},
		pluck="name",
	)
	for name in masters:
		replicate_to_company(frappe.get_doc("Salary Structure", name), doc.name)


def _matching_existing_children(template_doc, prefix: str) -> list[str]:
	rows = frappe.get_all(
		"Salary Structure",
		filters={"docstatus": 1, "is_active": "Yes", "is_master_template": 0, "name": ["!=", template_doc.name]},
		fields=["name", "source_template"],
	)
	matched = [
		r.name
		for r in rows
		if r.source_template == template_doc.name or r.name.startswith(f"{prefix} - ")
	]
	return sorted(matched)


@frappe.whitelist()
def get_replication_targets(template_name: str, scope: str = "outlets") -> dict:
	"""Return candidate companies without <prefix> - <Company>, plus existing child structures."""
	if not frappe.has_permission("Salary Structure", "create"):
		frappe.throw(_("Tidak punya izin membuat Salary Structure."), frappe.PermissionError)
	template = frappe.get_doc("Salary Structure", template_name)
	if not cint(template.get("is_master_template")) or template.docstatus != 1:
		frappe.throw(_("Dokumen harus berstatus Submitted dan dicentang Template Master."))
	prefix = resolve_prefix(template)
	all_companies = set(frappe.get_all("Company", pluck="name"))
	if scope == "outlets":
		candidates = all_companies & set(frappe.get_all("Outlet", pluck="name"))
	else:
		candidates = all_companies
	existing_prefix_companies = set(
		frappe.get_all(
			"Salary Structure",
			filters={"docstatus": ["<", 2], "name": ["like", f"{prefix} - %"]},
			pluck="company",
		)
	)
	missing = sorted(candidates - existing_prefix_companies)
	return {
		"prefix": prefix,
		"missing": missing,
		"existing": _matching_existing_children(template, prefix),
	}


@frappe.whitelist()
def apply_template(template_name: str, create_companies=None, sync_existing: int | bool = 0) -> dict:
	"""Replicate template_name to missing companies and/or update existing child structures."""
	if not frappe.has_permission("Salary Structure", "write"):
		frappe.throw(_("Tidak punya izin mengubah Salary Structure."), frappe.PermissionError)
	template = frappe.get_doc("Salary Structure", template_name)
	if not cint(template.get("is_master_template")) or template.docstatus != 1 or template.is_active != "Yes":
		frappe.throw(_("Template Master harus berstatus Submitted dan Active."))

	if isinstance(create_companies, str):
		create_companies = json.loads(create_companies)
	create_companies = list(create_companies or [])

	created = []
	for company in create_companies:
		name = replicate_to_company(template, company)
		if name:
			created.append(name)

	updated = []
	if cint(sync_existing):
		prefix = resolve_prefix(template)
		for child_name in _matching_existing_children(template, prefix):
			if sync_existing_child(template, child_name):
				updated.append(child_name)

	return {"created": created, "updated": updated}
