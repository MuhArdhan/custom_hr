"""Cocokkan Gaji: reading HR's salary sheet by column letter and finding the cells that differ from the draft slips."""

import unittest

import frappe

from custom_hr.api import payroll_match as svc


def mapping(*rows):
	return [frappe._dict(excel_column=column, salary_component=component) for column, component in rows]


GROUPS = svc.column_groups(mapping(("d", "Uang Makan"), ("E+F", "Upah Lembur"), ("E+F", "Lembur Driver"), ("G", "Kasbon")), {"Kasbon"})

SHEET = [
	("GAJI PT X",),
	(None, "NAMA", "NIP", "UANG MAKAN", "REGULER", "HOLIDAY", "KASBON"),
	(None, "A", 123456.0, 440000, 10000, 5000, None),
	(None, "B", "  654321 ", "=SUM(X)", None, None, 50000),
	(None, "C", None, 1, 1, 1, 1),  # the main table ends here
	(None, "D", 999999, 1, 1, 1, 1),
]


class TestPayrollMatch(unittest.TestCase):
	def test_columns_group_by_letters_and_only_one_component_groups_can_take_the_excel_value(self):
		self.assertEqual([(g.key, g.components, g.editable) for g in GROUPS], [("D", ["Uang Makan"], True), ("E+F", ["Upah Lembur", "Lembur Driver"], False), ("G", ["Kasbon"], False)])
		self.assertEqual(GROUPS[1].indexes, [4, 5])

	def test_a_bad_column_letter_is_refused(self):
		for column in ("", "C-D", "C+", "1A"):
			with self.subTest(column=column), self.assertRaises(frappe.ValidationError):
				svc.column_groups(mapping((column, "Uang Makan")), set())

	def test_the_sheet_is_read_from_the_nip_header_down_to_the_first_empty_nip(self):
		amounts, duplicates = svc.read_sheet(SHEET, GROUPS)
		self.assertEqual(amounts, {"123456": {"D": 440000, "E+F": 15000, "G": 0}, "654321": {"D": 0, "E+F": 0, "G": 50000}})
		self.assertEqual(duplicates, [])

	def test_a_nip_twice_is_reported_and_a_sheet_without_nip_is_refused(self):
		_, duplicates = svc.read_sheet([*SHEET[:3], SHEET[2]], GROUPS)
		self.assertEqual(duplicates, ["123456"])
		with self.assertRaises(frappe.ValidationError):
			svc.read_sheet([("NAMA", "GP")], GROUPS)

	def test_only_cells_off_by_more_than_one_rupiah_differ(self):
		slips = [
			frappe._dict(name="SS-1", employee="E1", employee_name="A", nip="123456", amounts={"Uang Makan": 440000.4, "Upah Lembur": 10000, "Lembur Driver": 2000}),
			frappe._dict(name="SS-2", employee="E2", employee_name="B", nip="654321", amounts={"Kasbon": 50000}),
			frappe._dict(name="SS-3", employee="E3", employee_name="C", nip="111111", amounts={}),
		]
		sheet = {"123456": {"D": 440000, "E+F": 15000, "G": 0}, "654321": {"D": 0, "E+F": 0, "G": 50000}, "777777": {"D": 1}}
		result = svc.compare_rows(sheet, slips, GROUPS)
		self.assertEqual([(r.slip, r.cells) for r in result.rows], [("SS-1", {"E+F": {"system": 12000, "excel": 15000}})])
		self.assertEqual((result.matched, result.not_in_slips, [r.employee for r in result.not_in_excel]), (2, ["777777"], ["E3"]))
