"""Tunjangan Jabatan and Resiko moved from each Designation into one table in Payroll Settings (tab HRM).

Every designation with an amount becomes a row; the two Designation fields are then removed. Rows are inserted
directly: the Payroll Settings table field is a fixture, made only after patches run.
"""

import frappe

CHILD, PARENT, FIELD = "HRM Designation Allowance", "Payroll Settings", "designation_allowances"
OLD_FIELDS = ("tunjangan_jabatan", "tunjangan_resiko")


def execute():
	if all(frappe.db.has_column("Designation", field) for field in OLD_FIELDS):
		listed = set(frappe.get_all(CHILD, filters={"parenttype": PARENT}, pluck="designation"))
		rows = frappe.db.sql(
			"""SELECT name, tunjangan_jabatan, tunjangan_resiko FROM `tabDesignation`
			WHERE IFNULL(tunjangan_jabatan, 0) > 0 OR IFNULL(tunjangan_resiko, 0) > 0 ORDER BY name""",
			as_dict=True,
		)
		for idx, row in enumerate((r for r in rows if r.name not in listed), start=len(listed) + 1):
			doc = frappe.get_doc(
				{
					"doctype": CHILD,
					"parent": PARENT,
					"parenttype": PARENT,
					"parentfield": FIELD,
					"idx": idx,
					"designation": row.name,
					"tunjangan_jabatan": row.tunjangan_jabatan,
					"tunjangan_resiko": row.tunjangan_resiko,
				}
			)
			doc.set_new_name()
			doc.db_insert()
	for field in OLD_FIELDS:
		frappe.delete_doc("Custom Field", f"Designation-{field}", force=True, ignore_missing=True)
	frappe.clear_cache()
