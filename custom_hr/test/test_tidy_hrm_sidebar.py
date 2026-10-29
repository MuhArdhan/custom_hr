"""HRM sidebar layout: sections with child links; an administrator's own links are kept."""

import unittest

import frappe

from custom_hr.patches.tidy_hrm_sidebar import LAYOUT, tidy


class TestTidyHrmSidebar(unittest.TestCase):
	def sidebar(self, rows):
		# native child-table metadata, nothing is saved
		return frappe.get_doc({"doctype": "Workspace Sidebar", "items": rows})

	def test_links_sit_under_their_section_and_extra_links_stay_at_the_end(self):
		doc = self.sidebar([
			{"type": "Link", "label": "Pengajuan Lembur", "link_type": "DocType", "link_to": "Overtime Request"},
			{"type": "Link", "label": "Admin Report", "link_type": "Report", "link_to": "My Report", "icon": "star"},
		])
		tidy(doc)
		labels = [(row.type, row.label, row.child) for row in doc.items]
		self.assertEqual(labels[0], ("Link", "Home", 0))
		self.assertIn(("Section Break", "Lembur", 0), labels)
		self.assertIn(("Link", "Overtime List", 1), labels)
		self.assertEqual(labels[-1], ("Link", "Admin Report", 0))
		self.assertEqual(sum(1 for row in doc.items if row.link_to == "Overtime Request"), 1)  # no duplicate
		self.assertEqual([row.idx for row in doc.items], list(range(1, len(doc.items) + 1)))

	def test_running_twice_gives_the_same_sidebar(self):
		doc = self.sidebar([])
		tidy(doc)
		first = [(row.type, row.label, row.link_to) for row in doc.items]
		tidy(doc)
		self.assertEqual([(row.type, row.label, row.link_to) for row in doc.items], first)
		self.assertEqual(len(first), len(LAYOUT))
