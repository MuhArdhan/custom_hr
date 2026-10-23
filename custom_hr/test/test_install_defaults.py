"""Fresh install: singles are saved before fixtures exist, so no Link default may name a fixture."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe

from custom_hr import install

DOCTYPES = Path(__file__).resolve().parents[1] / "hrm" / "doctype"


class TestInstallDefaults(unittest.TestCase):
	def test_no_link_field_of_a_single_defaults_to_a_record(self):
		# init_singles() validates Links before fixtures are imported, so such a default
		# aborts `install-app` on a new site (e.g. Frappe Cloud).
		offenders = []
		for path in DOCTYPES.glob("*/*.json"):
			doctype = json.loads(path.read_text())
			if doctype.get("doctype") != "DocType" or not doctype.get("issingle"):
				continue
			offenders += [
				f"{doctype['name']}.{field['fieldname']}"
				for field in doctype.get("fields", [])
				if field.get("fieldtype") == "Link" and field.get("default")
			]
		self.assertEqual(offenders, [])

	def test_overtime_component_is_filled_after_fixtures_when_empty(self):
		with patch("frappe.db.get_single_value", return_value=None), patch("frappe.db.exists", return_value=True), patch(
			"frappe.db.set_single_value"
		) as save:
			install.set_default_overtime_component()
		save.assert_called_once_with("HRM Payroll Settings", "overtime_salary_component", "Lembur")

	def test_an_existing_choice_is_kept(self):
		with patch("frappe.db.get_single_value", return_value="Lembur Khusus"), patch("frappe.db.exists", return_value=True), patch(
			"frappe.db.set_single_value"
		) as save:
			install.set_default_overtime_component()
		save.assert_not_called()

	def test_nothing_happens_when_the_fixture_component_is_missing(self):
		with patch("frappe.db.get_single_value", return_value=None), patch("frappe.db.exists", return_value=False), patch(
			"frappe.db.set_single_value"
		) as save:
			install.set_default_overtime_component()
		save.assert_not_called()
