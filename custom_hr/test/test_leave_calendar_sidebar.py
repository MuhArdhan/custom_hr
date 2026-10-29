import unittest

import frappe

from custom_hr.patches.add_leave_calendar_sidebar import insert_calendar


class TestLeaveCalendarSidebar(unittest.TestCase):
	def doc(self, field, rows):
		# Native child-table metadata is used, but nothing is saved.
		return frappe.get_doc({"doctype": "Workspace Sidebar", field: rows})

	def test_insert_before_leave_application_preserves_other_rows(self):
		for field in ["items"]:
			doc = self.doc(field, [
				{"type": "Link", "label": "Home", "link_type": "Workspace", "link_to": "Leaves"},
				{"type": "Link", "label": "Leave Application", "link_type": "DocType", "link_to": "Leave Application"},
				{"type": "Link", "label": "Custom Report", "link_type": "Report", "link_to": "My Report"},
			])
			self.assertTrue(insert_calendar(doc, field))
			self.assertEqual([r.label for r in doc.get(field)], ["Home", "Working Calendar", "Leave Application", "Custom Report"])
			self.assertEqual([r.idx for r in doc.get(field)], [1, 2, 3, 4])
			self.assertFalse(insert_calendar(doc, field))
			self.assertEqual(len(doc.get(field)), 4)

	def test_append_when_there_is_no_leave_application(self):
		doc = self.doc("items", [])
		self.assertTrue(insert_calendar(doc, "items"))
		self.assertEqual(doc.items[0].link_to, "leave-calendar")
