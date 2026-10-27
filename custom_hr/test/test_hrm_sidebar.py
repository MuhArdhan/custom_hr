import unittest

import frappe

from custom_hr.patches.add_hrm_sidebar_links import add_links

HRM_ROWS = [
	{"type": "Link", "label": "Home", "link_type": "Workspace", "link_to": "HRM"},
	{"type": "Link", "label": "Employee Attendance Gallery", "link_type": "Page", "link_to": "employee-attendance-gallery"},
	{"type": "Link", "label": "Roster Outlet", "link_type": "Page", "link_to": "outlet-roster"},
	{"type": "Link", "label": "Pengajuan Lembur", "link_type": "DocType", "link_to": "Overtime Request"},
]


class TestHrmSidebar(unittest.TestCase):
	def doc(self, rows=HRM_ROWS):
		# Native child-table metadata is used, but nothing is saved.
		return frappe.get_doc({"doctype": "Workspace Sidebar", "items": [dict(row) for row in rows]})

	def test_links_land_next_to_related_pages_and_settings_at_the_end(self):
		doc = self.doc()
		self.assertTrue(add_links(doc))
		self.assertEqual([r.label for r in doc.items], [
			"Home", "Employee Attendance Gallery", "Grooming Gallery", "Attendance", "Grooming", "Roster Outlet", "Outlet",
			"Pengajuan Lembur", "Contract Notification Settings", "Contract Notification Log", "HRM Payroll Settings",
		])
		self.assertEqual([r.idx for r in doc.items], list(range(1, 12)))

	def test_existing_rows_are_preserved_and_new_ones_are_plain_links(self):
		doc = self.doc()
		add_links(doc)
		self.assertEqual([r.link_to for r in doc.items if r.label in {"Home", "Roster Outlet", "Pengajuan Lembur"}], ["HRM", "outlet-roster", "Overtime Request"])
		outlet = next(r for r in doc.items if r.link_to == "Outlet")
		self.assertEqual((outlet.type, outlet.link_type), ("Link", "DocType"))

	def test_running_twice_adds_nothing(self):
		doc = self.doc()
		add_links(doc)
		self.assertFalse(add_links(doc))
		self.assertEqual(len(doc.items), 11)

	def test_a_link_the_admin_already_added_is_not_duplicated(self):
		doc = self.doc(HRM_ROWS + [{"type": "Link", "label": "Daftar Outlet", "link_type": "DocType", "link_to": "Outlet"}])
		add_links(doc)
		self.assertEqual(len([r for r in doc.items if r.link_to == "Outlet"]), 1)

	def test_falls_back_to_the_end_when_the_anchor_page_is_missing(self):
		doc = self.doc([HRM_ROWS[0]])
		add_links(doc)
		self.assertEqual([r.label for r in doc.items][:5], ["Home", "Attendance", "Grooming", "Grooming Gallery", "Outlet"])
