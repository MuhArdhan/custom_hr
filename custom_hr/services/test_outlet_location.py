"""Sync rules; existing locations/radii and locked attendance are not rewritten."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.services.outlet_location import sync_outlet_location


class TestOutletLocation(unittest.TestCase):
	def setUp(self):
		self.doc = frappe.get_doc({
			"doctype": "Outlet", "name": "TEST-OUTLET", "company": "TEST-OUTLET",
			"latitude": -7.1234567, "longitude": 110.7654321,
			"geofence_radius_m": 100,
		})
		self.location = MagicMock()
		self.location.name = "LINKED"
		self.location.latitude = -7.0
		self.location.longitude = 110.0
		self.location.checkin_radius = 250
		self.location.insert.return_value = self.location

	def tearDown(self):
		frappe.clear_messages()

	def test_new_coordinates_create_native_location_with_zero_radius(self):
		with patch("frappe.db.exists", return_value=False), patch("frappe.get_doc", return_value=self.location) as factory:
			sync_outlet_location(self.doc)
		payload = factory.call_args.args[0]
		self.assertEqual(payload["doctype"], "Shift Location")
		self.assertEqual(payload["location_name"], "Outlet - TEST-OUTLET")
		self.assertEqual(payload["latitude"], -7.1234567)
		self.assertEqual(payload["checkin_radius"], 0)
		self.assertEqual(self.doc.shift_location, "LINKED")

	def test_migration_preserves_legacy_radius_only_on_creation(self):
		with patch("frappe.db.exists", return_value=False), patch("frappe.get_doc", return_value=self.location) as factory:
			sync_outlet_location(self.doc, migrate=True)
		self.assertEqual(factory.call_args.args[0]["checkin_radius"], 100)

	def test_blank_coordinates_do_not_create_location(self):
		self.doc.latitude = self.doc.longitude = 0
		with patch("frappe.get_doc") as factory:
			sync_outlet_location(self.doc)
		factory.assert_not_called()

	def test_first_link_after_repairing_legacy_coordinates_preserves_radius(self):
		old = frappe._dict(shift_location=None, latitude=0, longitude=0)
		with patch.object(self.doc, "get_doc_before_save", return_value=old), patch("frappe.db.exists", return_value=False), patch("frappe.get_doc", return_value=self.location) as factory:
			sync_outlet_location(self.doc)
		self.assertEqual(factory.call_args.args[0]["checkin_radius"], 100)

	def test_out_of_range_coordinate_is_rejected_before_any_insert(self):
		self.doc.latitude = -76147929
		with patch("frappe.get_doc") as factory, self.assertRaisesRegex(frappe.ValidationError, "Koordinat Outlet tidak valid"):
			sync_outlet_location(self.doc)
		factory.assert_not_called()

	def test_conflicting_name_never_overwrites_an_existing_master(self):
		with patch("frappe.db.exists", return_value=True), patch("frappe.get_doc") as factory, self.assertRaisesRegex(frappe.ValidationError, "sudah ada"):
			sync_outlet_location(self.doc)
		factory.assert_not_called()

	def test_linked_location_coordinate_update_keeps_native_radius(self):
		self.doc.shift_location = "LINKED"
		old = frappe._dict(shift_location="LINKED", latitude=-7, longitude=110)
		with patch.object(self.doc, "get_doc_before_save", return_value=old), patch("frappe.db.get_value", return_value=None), patch("frappe.get_doc", return_value=self.location):
			sync_outlet_location(self.doc)
		self.assertEqual(self.location.latitude, -7.1234567)
		self.assertEqual(self.location.longitude, 110.7654321)
		self.assertEqual(self.location.checkin_radius, 250)
		self.location.save.assert_called_once()

	def test_unchanged_outlet_adopts_live_location_instead_of_overwriting_it(self):
		self.doc.shift_location = "LINKED"
		old = frappe._dict(shift_location="LINKED", latitude=self.doc.latitude, longitude=self.doc.longitude)
		with patch.object(self.doc, "get_doc_before_save", return_value=old), patch("frappe.db.get_value", return_value=None), patch("frappe.get_doc", return_value=self.location):
			sync_outlet_location(self.doc)
		self.location.save.assert_not_called()
		self.assertEqual((self.doc.latitude, self.doc.longitude), (-7, 110))
		self.assertEqual(self.doc.checkin_radius, 250)

	def test_selecting_existing_link_adopts_its_coordinates(self):
		self.doc.shift_location = "LINKED"
		with patch("frappe.db.get_value", return_value=None), patch("frappe.get_doc", return_value=self.location):
			sync_outlet_location(self.doc)
		self.location.insert.assert_not_called()
		self.location.save.assert_not_called()
		self.assertEqual(self.doc.latitude, -7)

	def test_shared_outlet_location_is_rejected(self):
		self.doc.shift_location = "LINKED"
		with patch("frappe.db.get_value", return_value="OTHER-OUTLET"), self.assertRaisesRegex(frappe.ValidationError, "sudah dipakai"):
			sync_outlet_location(self.doc)

	def test_clearing_link_cannot_generate_duplicate(self):
		with patch.object(self.doc, "get_doc_before_save", return_value=frappe._dict(shift_location="LINKED", latitude=self.doc.latitude, longitude=self.doc.longitude)), self.assertRaisesRegex(frappe.ValidationError, "tidak boleh dikosongkan"):
			sync_outlet_location(self.doc)

	def test_zero_axis_is_supported(self):
		self.doc.latitude = 0
		with patch("frappe.db.exists", return_value=False), patch("frappe.get_doc", return_value=self.location) as factory:
			sync_outlet_location(self.doc)
		self.assertEqual(factory.call_args.args[0]["latitude"], 0)

	def test_long_outlet_name_produces_a_stable_native_location_name(self):
		self.doc.name = "A" * 140
		with patch("frappe.db.exists", return_value=False), patch("frappe.get_doc", return_value=self.location) as factory:
			sync_outlet_location(self.doc)
		self.assertLessEqual(len(factory.call_args.args[0]["location_name"]), 140)
