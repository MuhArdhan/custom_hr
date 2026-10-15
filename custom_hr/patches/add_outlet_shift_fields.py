# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Scoped, repeatable T03 schema migration; never enables outlet attendance."""

import json
from pathlib import Path

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

OUTLET_SHIFT_FIELDS = {
	"Employee Checkin": (
		"outlet_shift_section",
		"attendance_source",
		"outlet_at_checkin",
		"shift_work_date",
		"outlet_shift_column",
		"paired_checkin",
		"checkout_deadline",
		"shift_policy_snapshot",
	),
	"Attendance": (
		"outlet_attendance_section",
		"attendance_source",
		"outlet_at_checkin",
		"source_checkin",
		"source_checkout",
		"outlet_attendance_column",
		"missing_checkout",
		"working_hours_source",
	),
}


def get_outlet_shift_custom_fields() -> dict[str, list[dict]]:
	"""Use the same definitions as normal install/migrate fixture import."""
	fixture_path = Path(frappe.get_app_path("custom_hr", "fixtures", "custom_field.json"))
	fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
	result = {}
	for doctype, names in OUTLET_SHIFT_FIELDS.items():
		fields = [field for field in fixtures if field["dt"] == doctype and field["fieldname"] in names]
		if len(fields) != len(names) or {field["fieldname"] for field in fields} != set(names):
			frappe.throw(_("Definisi fixture shift outlet untuk {0} tidak lengkap atau duplikat.").format(doctype))
		result[doctype] = fields
	return result


def execute():
	fields = get_outlet_shift_custom_fields()
	# Stop before DDL if a field belongs to another customization or its type
	# conflicts. Do not overwrite unknown work or convert existing data types.
	for doctype, definitions in fields.items():
		meta = frappe.get_meta(doctype)
		for definition in definitions:
			name = f"{doctype}-{definition['fieldname']}"
			if frappe.db.exists("Custom Field", name):
				existing = frappe.get_doc("Custom Field", name)
				if (
					existing.module != "HRM"
					or existing.fieldtype != definition["fieldtype"]
					or (existing.options or "") != definition.get("options", "")
				):
					frappe.throw(_("Custom Field {0} sudah ada dengan definisi berbeda. Periksa sebelum migrasi.").format(name))
			elif meta.has_field(definition["fieldname"]):
				frappe.throw(_("Field {0} sudah digunakan. Migrasi tidak akan menimpanya.").format(name))

	frappe.reload_doc("hrm", "doctype", "outlet")
	create_custom_fields(fields, update=True)
