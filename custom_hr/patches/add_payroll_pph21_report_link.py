"""Place Rekap PPh 21 under the Reports section of the native Payroll sidebar."""

import frappe

from custom_hr.patches.add_hrm_sidebar_links import add_links

REPORT = "Rekap PPh 21"
REPORT_ANCHOR = "Salary Register"
REPORT_ROW = {"type": "Link", "label": REPORT, "link_type": "Report", "link_to": REPORT}


def execute():
	try:
		from frappe.desk.doctype.custom_sidebar.custom_sidebar import (
			SITE_LAYER,
			add_site_sidebar_item,
			base_items,
			get_customization,
			get_layers,
			merge_layers,
		)
		from frappe.desk.doctype.sidebar.sidebar import LINKED_IDENTITY_FIELDS, is_linked, item_key
	except ImportError:
		return add_to_workspace_sidebar()

	existing = get_customization("Payroll", None)
	doc = (
		frappe.get_doc("Custom Sidebar", existing.name)
		if existing
		else frappe.new_doc("Custom Sidebar").update({"module": "Payroll", "user": SITE_LAYER})
	)

	old_rows = list(doc.sidebar_items)
	old_by_key = {item_key(old): old for old in old_rows}
	add_sal_section = next(
		(r.as_dict() for r in old_rows if r.get("added") and r.get("type") == "Section Break" and r.get("label") == "Additional Salary"),
		None,
	)
	input_page = next((r.as_dict() for r in old_rows if r.get("link_to") == "payroll-period-input"), None)

	rows = []
	inserted_report = False
	for item in base_items("Payroll"):
		if is_linked(item):
			row = {**{field: item.get(field) for field in LINKED_IDENTITY_FIELDS}, "child": item.get("child") or 0}
		else:
			row = {"type": item.get("type"), "key": item_key(item), "child": item.get("child") or 0}

		if item.get("link_to") == "Additional Salary" and add_sal_section and input_page:
			rows.append(add_sal_section)
			rows.append({**row, "child": 1})
			rows.append({**input_page, "child": 1, "added": 1})
			continue

		if item_key(row) in old_by_key and not old_by_key[item_key(row)].get("added"):
			saved = old_by_key[item_key(row)].as_dict()
			saved.pop("idx", None)
			saved.pop("name", None)
			saved["child"] = row["child"]
			row = saved
		rows.append(row)

		if item.get("link_to") == REPORT_ANCHOR and not inserted_report:
			rows.append({**REPORT_ROW, "added": 1, "child": 1})
			inserted_report = True

	if not inserted_report:
		return add_site_sidebar_item("Payroll", {**REPORT_ROW, "child": 1})

	handled = {"payroll-period-input", REPORT}
	for old in old_rows:
		if old.get("added") and old.get("link_to") not in handled and not (
			old.get("type") == "Section Break" and old.get("label") == "Additional Salary"
		):
			extra = old.as_dict()
			extra.pop("idx", None)
			extra.pop("name", None)
			rows.append(extra)

	for r in (add_sal_section, input_page):
		if r:
			r.pop("idx", None)
			r.pop("name", None)

	doc.set("sidebar_items", [])
	for idx, row in enumerate(rows, start=1):
		row["idx"] = idx
		doc.append("sidebar_items", row)
	doc.save(ignore_permissions=True)


def add_to_workspace_sidebar():
	if not frappe.db.exists("Workspace Sidebar", "Payroll"):
		return
	doc = frappe.get_doc("Workspace Sidebar", "Payroll")
	if add_links(doc, [(REPORT, "Report", REPORT, "", REPORT_ANCHOR)]):
		doc.flags.ignore_links = True
		doc.save(ignore_permissions=True)
