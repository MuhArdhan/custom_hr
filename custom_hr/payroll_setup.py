"""Install custom fields without editing the native Salary Slip DocType."""


def install_attendance_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields({"Salary Slip": [
		{"fieldname": "custom_hr_attendance_section", "fieldtype": "Section Break",
			"label": "Rincian Presensi Payroll", "insert_after": "deductions", "collapsible": 1},
		{"fieldname": "custom_hr_attendance_snapshot", "fieldtype": "Long Text",
			"label": "Snapshot Presensi JSON",
			"insert_after": "custom_hr_attendance_section", "read_only": 1, "no_copy": 1},
		{"fieldname": "custom_hr_attendance_hash", "fieldtype": "Data",
			"label": "Hash Sumber Presensi", "insert_after": "custom_hr_attendance_snapshot",
			"read_only": 1, "hidden": 1, "no_copy": 1},
		{"fieldname": "custom_hr_attendance_calculated_on", "fieldtype": "Datetime",
			"label": "Dihitung Pada", "insert_after": "custom_hr_attendance_hash", "read_only": 1, "no_copy": 1},
		{"fieldname": "custom_hr_attendance_warnings", "fieldtype": "Small Text",
			"label": "Catatan Verifikasi", "insert_after": "custom_hr_attendance_calculated_on",
			"read_only": 1, "no_copy": 1},
	]}, update=True)


def migrate_snapshot_json():
	"""Retire the snapshot child DocType only after copying and verifying its data."""
	import json
	from collections import defaultdict

	import frappe

	from custom_hr.api.payroll_attendance import DETAIL_FIELDS

	doctype = "HRM Attendance Payroll Detail"
	if not frappe.db.exists("DocType", doctype) and not frappe.db.exists(
		"Custom Field", "Salary Slip-custom_hr_attendance_breakdown"
	):
		return  # Archived rows must not overwrite snapshots refreshed after migration.
	if frappe.db.table_exists(doctype):
		rows = frappe.db.sql("select * from `tabHRM Attendance Payroll Detail` order by parent, idx",
			as_dict=True)
		grouped = defaultdict(list)
		for row in rows:
			if row.parenttype != "Salary Slip" or not frappe.db.exists("Salary Slip", row.parent):
				frappe.throw("Snapshot lama memiliki parent tidak valid; migrasi dihentikan agar data tidak hilang.")
			grouped[row.parent].append({field: row.get(field) for field in DETAIL_FIELDS})
		for name, details in grouped.items():
			existing = frappe.db.get_value("Salary Slip", name, "custom_hr_attendance_snapshot")
			if existing and json.loads(existing) != details:
				frappe.throw("Snapshot JSON dan tabel berbeda pada {0}; verifikasi sebelum migrasi.".format(name))
			frappe.db.set_value("Salary Slip", name, "custom_hr_attendance_snapshot",
				json.dumps(details, ensure_ascii=False), update_modified=False)
			stored = frappe.db.get_value("Salary Slip", name, "custom_hr_attendance_snapshot")
			if json.loads(stored) != details:
				frappe.throw("Verifikasi migrasi snapshot gagal pada {0}.".format(name))
	if frappe.db.exists("Custom Field", "Salary Slip-custom_hr_attendance_breakdown"):
		frappe.delete_doc("Custom Field", "Salary Slip-custom_hr_attendance_breakdown", ignore_permissions=True)
	if frappe.db.exists("DocType", doctype):
		frappe.delete_doc("DocType", doctype, ignore_permissions=True, force=True)
	# Retain the legacy SQL table as a recovery copy; no DROP TABLE is performed here.
	frappe.clear_cache(doctype="Salary Slip")


def migrate_company_policies():
	"""Copy legacy Single rows once; retain original rows as migration evidence."""
	import hashlib

	import frappe
	from frappe.utils import flt, getdate

	doctype = "HRM Attendance Payroll Settings"
	legacy = frappe.get_all("HRM Attendance Payroll Rule", filters={"parent": doctype,
		"parenttype": doctype}, fields=["*"])
	tolerance = frappe.db.sql("select value from tabSingles where doctype=%s and field=%s",
		(doctype, "late_tolerance_minutes"))
	groups = {}
	for row in legacy:
		if not row.company:
			frappe.throw("Aturan presensi lama belum memiliki perusahaan. Isi perusahaan sebelum migrasi.")
		groups.setdefault(row.company, []).append(row)
	for company, rows in groups.items():
		name = "HRM-APS-LEGACY-" + hashlib.sha256(company.encode()).hexdigest()[:12]
		if frappe.db.exists(doctype, name):
			continue
		doc = frappe.new_doc(doctype)
		doc.title = "Aturan Presensi - " + company
		doc.company = company
		doc.from_date = min(getdate(row.from_date) for row in rows)
		doc.to_date = max(getdate(row.to_date) for row in rows) if all(row.to_date for row in rows) else None
		doc.late_tolerance_minutes = flt(tolerance[0][0]) if tolerance else 0
		for row in rows:
			doc.append("rules", {field: row.get(field) for field in (
				"category", "salary_component", "unit", "hours_per_day", "enabled", "method", "rate", "divisor",
				"multiplier", "from_date", "to_date")})
		doc.insert(ignore_permissions=True, set_name=name)


def install_payroll_sidebar():
	"""Extend the live sidebar without exporting or changing HRMS source files."""
	import frappe

	if not frappe.db.exists("Workspace Sidebar", "Payroll"):
		return
	sidebar = frappe.get_doc("Workspace Sidebar", "Payroll")
	if any(row.link_to == "HRM Attendance Payroll Settings" for row in sidebar.items):
		return
	setup_index = next((i for i, row in enumerate(sidebar.items)
		if row.label == "Setup" and row.type == "Section Break"), None)
	if setup_index is None:
		sidebar.append("items", {"label": "Setup", "type": "Section Break"})
		setup_index = len(sidebar.items) - 1
	end = setup_index + 1
	while end < len(sidebar.items) and (sidebar.items[end].child or sidebar.items[end].label == "Setup"):
		end += 1
	item = sidebar.append("items", {"label": "Aturan Presensi Payroll", "type": "Link",
		"link_type": "DocType", "link_to": "HRM Attendance Payroll Settings", "child": 1})
	sidebar.items.remove(item)
	sidebar.items.insert(end, item)
	for index, row in enumerate(sidebar.items, 1):
		row.idx = index
	previous = frappe.flags.in_import
	try:
		frappe.flags.in_import = True  # Avoid exporting the standard sidebar into core HRMS.
		sidebar.save(ignore_permissions=True)
	finally:
		frappe.flags.in_import = previous


def install_payroll_setup():
	install_attendance_fields()
	migrate_snapshot_json()
	migrate_company_policies()
	install_payroll_sidebar()
