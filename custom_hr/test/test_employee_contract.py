import unittest
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.hrm.doctype.employee_contract.employee_contract import (
	EmployeeContract,
	get_contract_status,
	get_duration_end_date,
	get_renewal_defaults,
)


class TestEmployeeContract(unittest.TestCase):
	def contract(self, **overrides):
		return frappe._dict({
			"name": "CON-NEW", "employee": "EMP-1", "docstatus": 0, "contract_type": "PKWT",
			"start_date": "2026-10-17", "end_date": "2027-10-16", "previous_contract": None,
			"contract_file": "/private/files/contract.pdf", **overrides,
		})

	def test_status_draft_and_cancelled(self):
		self.assertEqual(get_contract_status(self.contract(), "2026-10-13"), "Draft")
		self.assertEqual(get_contract_status(self.contract(docstatus=2), "2026-10-13"), "Dibatalkan")

	def test_status_is_date_driven(self):
		doc = self.contract(docstatus=1)
		self.assertEqual(get_contract_status(doc, "2026-10-13"), "Belum Berlaku")
		self.assertEqual(get_contract_status(doc, "2026-10-17"), "Aktif")
		self.assertEqual(get_contract_status(doc, "2027-10-16"), "Aktif")
		self.assertEqual(get_contract_status(doc, "2027-10-17"), "Berakhir")

	def test_indefinite_contract_status(self):
		self.assertEqual(get_contract_status(self.contract(docstatus=1, end_date=None), "2030-01-01"), "Aktif")

	def test_date_validation(self):
		for changes in [{"start_date": None}, {"end_date": None}, {"end_date": "2026-10-16"},
			{"contract_type": "PKWTT"}, {"contract_type": "invalid"}]:
			with self.subTest(changes=changes), patch.object(frappe, "throw", side_effect=ValueError):
				with self.assertRaises(ValueError):
					EmployeeContract.validate_dates(self.contract(**changes))
		EmployeeContract.validate_dates(self.contract())
		EmployeeContract.validate_dates(self.contract(contract_type="PKWTT", end_date=None))

	def test_preset_duration_end_dates(self):
		for duration, end in [("3 bulan", "2026-03-31"), ("6 bulan", "2026-06-30"),
			("12 bulan", "2026-12-31"), ("24 bulan", "2027-12-31")]:
			with self.subTest(duration=duration):
				self.assertEqual(str(get_duration_end_date("2026-01-01", duration)), end)
		self.assertIsNone(get_duration_end_date("2026-01-01", "Custom"))

	def test_month_end_and_leap_year_duration(self):
		self.assertEqual(str(get_duration_end_date("2026-01-31", "3 bulan")), "2026-04-29")
		self.assertEqual(str(get_duration_end_date("2023-12-01", "3 bulan")), "2024-02-29")

	def test_server_calculates_missing_end_for_preset(self):
		doc = self.contract(start_date="2026-01-01", end_date=None, contract_duration="3 bulan")
		EmployeeContract.validate_dates(doc)
		self.assertEqual(str(doc.end_date), "2026-03-31")

	def test_preset_mismatch_requires_custom(self):
		with patch.object(frappe, "throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				EmployeeContract.validate_dates(self.contract(contract_duration="3 bulan"))
		EmployeeContract.validate_dates(self.contract(contract_duration="Custom"))

	def test_renewal_validates_previous_contract(self):
		previous = MagicMock()
		previous.docstatus = 1
		previous.employee = "EMP-1"
		previous.contract_type = "PKWT"
		previous.end_date = "2026-10-16"
		with patch.object(frappe, "get_doc", return_value=previous):
			EmployeeContract.validate_previous_contract(self.contract(previous_contract="CON-OLD"))
		previous.check_permission.assert_called_once_with("read")

	def test_renewal_rejects_overlap_other_employee_and_draft(self):
		for changes in [{"employee": "EMP-2"}, {"docstatus": 0}, {"contract_type": "PKWTT"},
			{"end_date": "2026-10-17"}]:
			previous = frappe._dict(docstatus=1, employee="EMP-1", contract_type="PKWT",
				end_date="2026-10-16", check_permission=MagicMock())
			previous.update(changes)
			with self.subTest(changes=changes), patch.object(frappe, "get_doc", return_value=previous):
				with patch.object(frappe, "throw", side_effect=ValueError):
					with self.assertRaises(ValueError):
						EmployeeContract.validate_previous_contract(self.contract(previous_contract="CON-OLD"))

	def test_requires_private_existing_file(self):
		with patch.object(frappe, "throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				EmployeeContract.validate_private_file(self.contract(contract_file="/files/public.pdf"))
			with patch.object(frappe, "db", MagicMock()) as db:
				db.get_value.return_value = None
				with self.assertRaises(ValueError):
					EmployeeContract.validate_private_file(self.contract())

	def test_submit_requires_attachment(self):
		with patch.object(frappe, "throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				EmployeeContract.before_submit(self.contract(contract_file=None))

	def test_submit_rejects_overlap(self):
		with patch.object(frappe, "db", MagicMock()) as db:
			db.sql.side_effect = [[], [self.contract(name="CON-EXISTING")]]
			with patch.object(frappe, "throw", side_effect=ValueError):
				with self.assertRaises(ValueError):
					EmployeeContract.before_submit(self.contract())
		self.assertIn("for update", db.sql.call_args_list[0].args[0])
		self.assertIn("for update", db.sql.call_args_list[1].args[0])

	def test_submit_allows_non_overlapping_contract(self):
		with patch.object(frappe, "db", MagicMock()) as db:
			db.sql.side_effect = [[], [self.contract(start_date="2025-10-17", end_date="2026-10-16")]]
			EmployeeContract.before_submit(self.contract())

	def test_one_submitted_renewal_per_previous_contract(self):
		with patch.object(frappe, "db", MagicMock()) as db:
			db.sql.side_effect = [[], [self.contract(previous_contract="CON-OLD", start_date="2028-01-01")]]
			with patch.object(frappe, "throw", side_effect=ValueError):
				with self.assertRaises(ValueError):
					EmployeeContract.before_submit(self.contract(previous_contract="CON-OLD"))

	def test_renewal_defaults_do_not_copy_attachment_or_end_date(self):
		previous = MagicMock()
		previous.docstatus, previous.contract_type, previous.end_date = 1, "PKWT", "2026-10-16"
		previous.employee, previous.name = "EMP-1", "CON-OLD"
		with patch.object(frappe, "get_doc", return_value=previous):
			with patch.object(frappe, "has_permission", return_value=True):
				defaults = get_renewal_defaults("CON-OLD")
		self.assertEqual(str(defaults["start_date"]), "2026-10-17")
		self.assertEqual(defaults["previous_contract"], "CON-OLD")
		self.assertNotIn("end_date", defaults)
		self.assertNotIn("contract_file", defaults)

	def test_renewal_requires_create_permission(self):
		with patch.object(frappe, "get_doc", return_value=MagicMock()):
			with patch.object(frappe, "has_permission", return_value=False):
				with patch.object(frappe, "throw", side_effect=PermissionError):
					with self.assertRaises(PermissionError):
						get_renewal_defaults("CON-OLD")
