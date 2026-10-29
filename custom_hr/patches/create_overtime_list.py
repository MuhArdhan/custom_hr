"""Write the Overtime List rows of overtime approved before the list existed."""

import frappe


def execute():
	frappe.reload_doc("hrm", "doctype", "overtime_list")
	approved = frappe.db.sql(
		"""
		select distinct otr.name
		from `tabOvertime Request` otr
		join `tabOvertime Request Employee` otre on otre.parent = otr.name and otre.parenttype = 'Overtime Request'
		where COALESCE(NULLIF(otre.approval_state, ''), otr.status) = 'Disetujui'
		""",
		pluck=True,
	)
	for name in approved:
		frappe.get_doc("Overtime Request", name).sync_overtime_list()
