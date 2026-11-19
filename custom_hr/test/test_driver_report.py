"""Laporan Posisi Driver: who may report, from when, and which positions are real."""

import unittest
from datetime import datetime, time
from unittest.mock import patch

from custom_hr.api import driver_report as svc
from custom_hr.hrm.doctype.laporan_posisi_driver.laporan_posisi_driver import maps_url


class TestDriverReport(unittest.TestCase):
	def test_only_driver_designations_report(self):
		self.assertTrue(svc.is_driver("DRIVER"))
		self.assertTrue(svc.is_driver("Gudang & Driver JKT"))
		self.assertFalse(svc.is_driver("TEKNISI"))
		self.assertFalse(svc.is_driver(None))

	def test_open_from_the_set_time_until_midnight(self):
		opens = time(16, 30)
		self.assertFalse(svc.is_open(datetime(2026, 11, 19, 16, 29, 59), opens))
		self.assertTrue(svc.is_open(datetime(2026, 11, 19, 16, 30), opens))
		self.assertTrue(svc.is_open(datetime(2026, 11, 19, 23, 59), opens))
		self.assertFalse(svc.is_open(datetime(2026, 11, 20, 0, 5), opens))

	def test_the_time_comes_from_payroll_settings_else_1630(self):
		with patch.object(svc.frappe.db, "get_single_value", return_value="17:15:00"):
			self.assertEqual(svc.opens_at(), time(17, 15))
		with patch.object(svc.frappe.db, "get_single_value", return_value=None):
			self.assertEqual(svc.opens_at(), time(16, 30))

	def test_a_missing_or_impossible_position_is_refused(self):
		self.assertTrue(svc.valid_position(-7.0, 110.4))
		self.assertTrue(svc.valid_position("-7.0", "110.4"))
		for bad in ((None, 110.4), ("", ""), (0, 0), (91, 10), (10, 181), ("x", 1)):
			self.assertFalse(svc.valid_position(*bad), bad)

	def test_the_gallery_filters_by_period_and_seen_state_for_page_users_only(self):
		with patch.object(svc, "require_page_access") as only_for, patch.object(svc.frappe, "get_all", return_value=[]) as get_all, patch.object(svc.frappe.db, "count", return_value=0):
			svc.get_driver_report_gallery(from_date="2026-11-01", to_date="2026-11-19", dilihat="0", company="Co", search="bud")
			only_for.assert_called_with("driver-position-gallery")
			filters = get_all.call_args.kwargs["filters"]
			self.assertEqual(filters, {"report_date": ["between", ["2026-11-01", "2026-11-19"]], "company": "Co", "dilihat": 0, "employee_name": ["like", "%bud%"]})
			svc.get_driver_report_gallery(to_date="2026-11-19", dilihat="")
			self.assertEqual(get_all.call_args.kwargs["filters"], {"report_date": ["between", ["2026-11-19", "2026-11-19"]]})
			with self.assertRaises(svc.frappe.ValidationError):
				svc.get_driver_report_gallery(from_date="2026-11-20", to_date="2026-11-19")

	def test_the_maps_link_opens_the_reported_spot(self):
		self.assertEqual(maps_url(-7.0, 110.4), "https://www.google.com/maps?q=-7.0,110.4")
		self.assertIsNone(maps_url(None, None))
