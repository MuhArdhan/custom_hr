"""Cocokkan Gaji: reading HR's salary sheet by column letter and finding the cells that differ from the draft slips."""

import base64
import io
import unittest
from unittest.mock import patch

import frappe
from openpyxl import Workbook

from custom_hr.api import payroll_match as svc


def mapping(*rows):
	return [frappe._dict(excel_column=column, salary_component=component) for column, component in rows]


GROUPS = svc.column_groups(mapping(("d", "Uang Makan"), ("E+F", "Upah Lembur"), ("E+F", "Lembur Driver"), ("G", "Kasbon")), {"Kasbon"})

SHEET = [
	("GAJI PT X",),
	(None, "NAMA", "NIP", "UANG MAKAN", "REGULER", "HOLIDAY", "KASBON"),
	(None, "A", 123456.0, 440000, 10000, 5000, None),
	(None, "B", "  654321 ", "=SUM(X)", None, None, 50000),
	(None, "C", None, 1, 1, 1, 1),  # employee without NIP yet: skipped, not end-of-table
	(None, "D", 999999, 100000, 0, 0, 0),
	(None, None, None, None, None, None, None),  # the main table ends here
	(None, "E", 888888, 1, 1, 1, 1),
]


class TestPayrollMatch(unittest.TestCase):
	def test_columns_group_by_letters_and_only_one_component_groups_can_take_the_excel_value(self):
		self.assertEqual([(g.key, g.components, g.editable) for g in GROUPS], [("D", ["Uang Makan"], True), ("E+F", ["Upah Lembur", "Lembur Driver"], False), ("G", ["Kasbon"], False)])
		self.assertEqual(GROUPS[1].indexes, [4, 5])

	def test_a_bad_column_letter_is_refused(self):
		for column in ("", "C-D", "C+", "1A"):
			with self.subTest(column=column), self.assertRaises(frappe.ValidationError):
				svc.column_groups(mapping((column, "Uang Makan")), set())

	def test_the_sheet_skips_missing_nip_rows_and_stops_at_table_end(self):
		amounts, duplicates = svc.read_sheet(SHEET, GROUPS)
		self.assertEqual(
			amounts,
			{
				"123456": {"D": 440000, "E+F": 15000, "G": 0},
				"654321": {"D": 0, "E+F": 0, "G": 50000},
				"999999": {"D": 100000, "E+F": 0, "G": 0},
			},
		)
		self.assertEqual(duplicates, [])
		with_notes = [*SHEET[:4], (None, "Catatan :", None, 1, 1, 1, 1), *SHEET[5:]]
		notes_amounts, _ = svc.read_sheet(with_notes, GROUPS)
		self.assertEqual(set(notes_amounts), {"123456", "654321"})

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

	def test_matching_by_name_accepts_nama_headers_normalizes_whitespace_and_guards_duplicates(self):
		outlet_sheet = [
			("OUTLET",),
			(None, "NAMA CREW", None, "UANG MAKAN", "REGULER", "HOLIDAY", "KASBON"),
			(None, "  budi   santoso ", None, 440000, 10000, 5000, None),
			(None, "Siti Aminah", None, 300000, 0, 0, 50000),
			(None, "SITI  AMINAH", None, 100000, 0, 0, 0),
			(None, "", None, 1, 1, 1, 1),
		]
		amounts, duplicates = svc.read_sheet(outlet_sheet, GROUPS, match_by="name")
		self.assertEqual(duplicates, ["SITI AMINAH"])
		for dup in duplicates:
			amounts.pop(dup)
		self.assertEqual(amounts, {"BUDI SANTOSO": {"D": 440000, "E+F": 15000, "G": 0}})

		slips = [
			frappe._dict(name="SS-1", employee="E1", employee_name="Budi Santoso", nip="", amounts={"Uang Makan": 400000, "Upah Lembur": 15000}),
			frappe._dict(name="SS-2", employee="E2", employee_name="Dewi", nip="", amounts={"Uang Makan": 100000}),
			frappe._dict(name="SS-3", employee="E3", employee_name="Rina", nip="", amounts={"Uang Makan": 100000}),
			frappe._dict(name="SS-4", employee="E4", employee_name="RINA", nip="", amounts={"Uang Makan": 200000}),
		]
		result = svc.compare_rows(amounts, slips, GROUPS, match_by="name")
		self.assertEqual([(r.slip, r.cells) for r in result.rows], [("SS-1", {"D": {"system": 400000, "excel": 440000}})])
		self.assertEqual(result.duplicate_slips, ["RINA"])
		self.assertEqual((result.matched, result.not_in_slips, [r.employee for r in result.not_in_excel]), (1, [], ["E2"]))

	def test_missing_name_header_or_bad_match_by_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			svc.read_sheet([("NIP", "GP")], GROUPS, match_by="name")
		with self.assertRaises(frappe.ValidationError):
			svc.read_sheet(SHEET, GROUPS, match_by="email")

	def test_auto_detect_handles_ph_two_row_shifted_headers_and_stops_before_email(self):
		row4 = ["", "", "", "", "LEMBUR", "", "", "", "POTONGAN", "", "", "", "", "UANG MAKAN", "TRANSPORT", "SHIFT PAGI", "", "SHIFT SIANG", "", "", "", "", ""]
		row5 = ["NIP", "NAMA", "GP", "GP + TUNJANGAN TETAP", "REGULER", None, "HOLIDAY", None, "ALPHA", None, "TERLAMBAT", None, "KASBON", None, None, None, "RP. 8000", None, "RP. 12000", "BPJS KS ( 1%)", "BPJS KT (2%)", "EMAIL", "BPJS Kesehatan"]
		groups, options = svc.auto_detect_groups(
			[row4, row5],
			match_by="nip",
			period_input={"Kasbon"},
			db_components=["Gaji Pokok", "Lembur Reguler", "Lembur Holiday", "Alpha", "Terlambat", "Kasbon", "Uang Makan", "Tunjangan Transport", "Tunjangan Shift", "BPJS Kesehatan", "BPJS Ketenagakerjaan"],
		)
		mapped = {tuple(g.components): g.key for g in groups}
		self.assertEqual(mapped[("Gaji Pokok",)], "C")
		self.assertEqual(mapped[("Lembur Reguler",)], "F")
		self.assertEqual(mapped[("Lembur Holiday",)], "H")
		self.assertEqual(mapped[("Alpha",)], "J")
		self.assertEqual(mapped[("Terlambat",)], "L")
		self.assertEqual(mapped[("Kasbon",)], "M")
		self.assertEqual(mapped[("Uang Makan",)], "N")
		self.assertEqual(mapped[("Tunjangan Transport",)], "O")
		self.assertEqual(mapped[("Tunjangan Shift",)], "Q+S")
		self.assertEqual(mapped[("BPJS Kesehatan",)], "T")
		self.assertEqual(mapped[("BPJS Ketenagakerjaan",)], "U")
		self.assertNotIn("W", [o["key"] for o in options])  # stopped at EMAIL

	def test_auto_detect_handles_outlet_sheet_headers_and_izin_variant(self):
		row = ["NAMA CREW", "Total", "Pokok Proporsional", "Harian Proporsional", "Take Home Pay", "Pending", "Tunj Jabatan", "JAM Lembur", "Lembur", "JUMLAH TELAT", "POTONGAN TELAT", "Potongan IZIN DLL", "PINALTY", "No. rek", "THP"]
		groups, options = svc.auto_detect_groups(
			[row],
			match_by="name",
			slip_components={"Gaji Pokok", "Uang Makan", "Lembur Reguler", "Terlambat", "Izin"},
			period_input={"Pending", "Izin", "Pinalty"},
			db_components=["Gaji Pokok", "Uang Makan", "Tunjangan Jabatan", "Lembur Reguler", "Terlambat", "Izin", "Potongan Izin", "Pinalty", "Pending"],
		)
		mapped = {tuple(g.components): (g.key, g.editable) for g in groups}
		self.assertEqual(mapped[("Gaji Pokok",)], ("C", True))
		self.assertEqual(mapped[("Uang Makan",)], ("D", True))
		self.assertEqual(mapped[("Pending",)], ("F", False))
		self.assertEqual(mapped[("Tunjangan Jabatan",)], ("G", True))
		self.assertEqual(mapped[("Lembur Reguler",)], ("I", True))
		self.assertEqual(mapped[("Terlambat",)], ("K", True))
		self.assertEqual(mapped[("Izin",)], ("L", False))
		self.assertEqual(mapped[("Pinalty",)], ("M", False))
		self.assertNotIn("O", [o["key"] for o in options])  # stopped at No. rek

	def test_compare_tolerates_empty_and_null_custom_columns(self):
		self.assertIsNone(svc._parse_json_arg(None))
		self.assertIsNone(svc._parse_json_arg(""))
		self.assertIsNone(svc._parse_json_arg("   "))
		self.assertIsNone(svc._parse_json_arg("null"))
		self.assertEqual(svc._parse_json_arg('[{"excel_column": "D", "salary_component": "Uang Makan"}]'), [{"excel_column": "D", "salary_component": "Uang Makan"}])

		wb = Workbook()
		ws = wb.active
		ws.title = "OKTOBER 2026"
		ws.append(["NIP", "NAMA", "GP", "UANG MAKAN"])
		ws.append(["123456", "Budi", 3000000, 440000])
		buf = io.BytesIO()
		wb.save(buf)
		content = base64.b64encode(buf.getvalue()).decode()

		slips = [frappe._dict(name="SS-1", employee="E1", employee_name="Budi", nip="123456", amounts={"Gaji Pokok": 3000000, "Uang Makan": 400000})]
		with patch.object(svc, "_entry", return_value=frappe._dict(name="PE-1")), patch.object(svc, "_slips", return_value=slips):
			for raw in ("", "   ", "null", None):
				with self.subTest(custom_columns=raw):
					res = svc.compare("PE-1", content, sheet="OKTOBER 2026", match_by="nip", mapping_mode="auto", custom_columns=raw)
					self.assertEqual(res.mapping_mode, "auto")
					self.assertEqual(res.matched, 1)
					self.assertEqual(len(res.rows), 1)
			custom_res = svc.compare(
				"PE-1",
				content,
				sheet="OKTOBER 2026",
				match_by="nip",
				mapping_mode="auto",
				custom_columns='[{"excel_column": "D", "salary_component": "Uang Makan"}]',
			)
			self.assertEqual(custom_res.mapping_mode, "custom")
			self.assertEqual([c["key"] for c in custom_res.columns], ["D"])

	def test_auto_detect_follows_overtime_type_component_changes(self):
		row4 = ["", "", "", "LEMBUR", "", ""]
		row5 = ["NIP", "NAMA", "GP", "REGULER", None, "HOLIDAY", None]
		groups, _ = svc.auto_detect_groups(
			[row4, row5],
			match_by="nip",
			db_components=["Gaji Pokok", "Lembur Biasa", "Lembur Merah"],
			overtime_components={"reguler": "Lembur Biasa", "holiday": "Lembur Merah"},
		)
		mapped = {tuple(g.components): g.key for g in groups}
		self.assertEqual(mapped[("Lembur Biasa",)], "E")
		self.assertEqual(mapped[("Lembur Merah",)], "G")

		merged, _ = svc.auto_detect_groups(
			[row4, row5],
			match_by="nip",
			db_components=["Gaji Pokok", "Lembur Biasa"],
			overtime_components={"reguler": "Lembur Biasa", "holiday": "Lembur Biasa"},
		)
		self.assertEqual({tuple(g.components): g.key for g in merged}[("Lembur Biasa",)], "E+G")
