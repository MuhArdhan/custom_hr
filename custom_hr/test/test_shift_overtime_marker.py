import unittest
from unittest.mock import patch

import frappe

from custom_hr.overrides import shift_type as module
from custom_hr.overrides.shift_type import CustomShiftType, overtime_marker


def shift(**values):
	doc = frappe.new_doc("Shift Type")
	doc.update(values)
	return doc


class TestShiftOvertimeMarker(unittest.TestCase):
	def fill(self, doc, existing):
		with patch.object(module.frappe.db, "exists", side_effect=lambda doctype, name: name in existing), patch.object(
			module.frappe, "get_all", return_value=sorted(existing)
		):
			CustomShiftType.fill_overtime_marker(doc)
		return doc.overtime_type

	def test_allow_overtime_alone_gets_lembur(self):
		self.assertEqual(self.fill(shift(allow_overtime=1), {"Lembur", "Hari Libur"}), "Lembur")

	def test_without_lembur_the_first_overtime_type_is_used(self):
		self.assertEqual(self.fill(shift(allow_overtime=1), {"Lembur Libur", "Akhir Pekan"}), "Akhir Pekan")

	def test_a_set_and_existing_type_is_kept(self):
		self.assertEqual(self.fill(shift(allow_overtime=1, overtime_type="Hari Libur"), {"Lembur", "Hari Libur"}), "Hari Libur")

	def test_a_deleted_type_is_replaced(self):
		self.assertEqual(self.fill(shift(allow_overtime=1, overtime_type="Dihapus"), {"Lembur"}), "Lembur")

	def test_no_overtime_means_no_marker(self):
		self.assertIsNone(self.fill(shift(allow_overtime=0), {"Lembur"}))

	def test_no_overtime_type_at_all_refuses_the_save(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Overtime Type"):
			self.fill(shift(allow_overtime=1), set())

	def test_the_real_marker_exists_on_this_site(self):
		self.assertTrue(overtime_marker())


class TestShiftOvertimeFieldHidden(unittest.TestCase):
	def test_the_overtime_type_field_is_hidden_and_not_mandatory(self):
		field = frappe.get_meta("Shift Type").get_field("overtime_type")
		self.assertEqual((field.hidden, field.mandatory_depends_on or ""), (1, ""))

	def test_a_new_shift_type_allows_overtime(self):
		self.assertEqual(str(frappe.get_meta("Shift Type").get_field("allow_overtime").default), "1")
		self.assertEqual(frappe.new_doc("Shift Type").allow_overtime, 1)
