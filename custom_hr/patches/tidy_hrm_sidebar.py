"""Group the HRM sidebar into collapsible sections, like the HRMS sidebars.

Links an administrator added that are not in the layout stay, at the end.
"""

import frappe

# (label, link_type, link_to, icon); a None link_type opens a section whose links follow
LAYOUT = [
	("Home", "Workspace", "HRM", "house"),
	("Absensi & Grooming", None, None, "camera"),
	("Employee Attendance Gallery", "Page", "employee-attendance-gallery", ""),
	("Attendance", "DocType", "Attendance", ""),
	("Grooming", "DocType", "Grooming Check", ""),
	("Grooming Gallery", "Page", "grooming-gallery", ""),
	("Outlet", None, None, "store"),
	("Roster Outlet", "Page", "outlet-roster", ""),
	("Outlet", "DocType", "Outlet", ""),
	("Lembur", None, None, "calendar-clock"),
	("Pengajuan Lembur", "DocType", "Overtime Request", ""),
	("Overtime List", "DocType", "Overtime List", ""),
	("Working Calendar", "Page", "leave-calendar", ""),
	("Reports", None, None, "notepad-text"),
	("Laporan Lembur", "Report", "Laporan Lembur", ""),
	("Perhitungan Lembur", "Report", "Perhitungan Lembur", ""),
	("Rekap Gaji per Departemen", "Report", "Rekap Gaji per Departemen", ""),
	("Setup", None, None, "database"),
	("HRM Payroll Settings", "DocType", "HRM Payroll Settings", ""),
	("Contract Notification Settings", "DocType", "Contract Notification Settings", ""),
	("Contract Notification Log", "DocType", "Contract Notification Log", ""),
]


def rows():
	"""The layout as sidebar rows; a link inside a section is a child row."""
	in_section = False
	for label, link_type, link_to, icon in LAYOUT:
		if link_type is None:
			in_section = True
			yield dict(type="Section Break", label=label, icon=icon, indent=1, collapsible=1, child=0)
		else:
			yield dict(type="Link", label=label, link_type=link_type, link_to=link_to, icon=icon, child=int(in_section), indent=0, collapsible=1)


def tidy(doc):
	placed = {(link_type, link_to) for _, link_type, link_to, _ in LAYOUT if link_type}
	extra = [row.as_dict() for row in doc.items if row.type == "Link" and (row.link_type, row.link_to) not in placed]
	doc.items = []
	for row in rows():
		doc.append("items", row)
	for row in extra:  # an administrator's own links are kept
		doc.append("items", {key: row[key] for key in ("type", "label", "link_type", "link_to", "url", "icon", "child", "indent", "collapsible", "filters", "route_options") if key in row})
	for index, item in enumerate(doc.items, 1):
		item.idx = index


def execute():
	if not frappe.db.exists("Workspace Sidebar", "HRM"):
		return
	previous_developer_mode = frappe.conf.developer_mode
	try:
		# Save without exporting files: saving in developer mode rewrites app files.
		frappe.conf.developer_mode = 0
		doc = frappe.get_doc("Workspace Sidebar", "HRM")
		tidy(doc)
		doc.save(ignore_permissions=True)
	finally:
		frappe.conf.developer_mode = previous_developer_mode
