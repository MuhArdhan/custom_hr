"""Grooming gallery API: filtered cards with their photos, and review straight from the gallery."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.api import grooming


def card(name, status="Menunggu"):
	return frappe._dict(name=name, employee="EMP-1", employee_name="Budi", company="Co", outlet=None, grooming_date="2026-10-26", submitted_at="2026-10-26 08:00:00", review_status=status, review_note=None)


def photo(parent, step, idx):
	return frappe._dict(parent=parent, step=step, photo=f"/private/files/{parent}-{step}.jpg", idx=idx)


class TestGroomingGallery(unittest.TestCase):
	def setUp(self):
		self.cards = [card("G1"), card("G2", "Sesuai")]
		self.photos = [photo("G1", "left_hand", 2), photo("G1", "right_hand", 1), photo("G2", "right_hand", 1)]
		self.calls = []
		self.only_for = self.patch("frappe.only_for")
		self.patch("frappe.get_all", side_effect=self.get_all)
		self.patch("custom_hr.api.grooming.nowdate", return_value="2026-10-26")

	def patch(self, target, **kwargs):
		patcher = patch(target, **kwargs)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def get_all(self, doctype, filters=None, fields=None, **kwargs):
		self.calls.append((doctype, dict(filters or {}), kwargs))
		if doctype == "Grooming Check":
			start, length = kwargs.get("start", 0), kwargs.get("page_length", 0)
			return self.cards[start : start + length]
		return [p for p in sorted(self.photos, key=lambda p: p.idx) if p.parent in filters["parent"][1]]

	def test_only_hr_roles_may_open_the_gallery_or_review(self):
		self.only_for.side_effect = frappe.PermissionError("nope")
		with self.assertRaises(frappe.PermissionError):
			grooming.get_grooming_gallery()
		with self.assertRaises(frappe.PermissionError):
			grooming.review_grooming("G1", "Sesuai")
		self.only_for.assert_called_with(("HR Manager", "HR User", "System Manager"))

	def test_cards_carry_their_photos_in_step_order_with_titles(self):
		rows = grooming.get_grooming_gallery()["rows"]
		self.assertEqual([r["name"] for r in rows], ["G1", "G2"])
		self.assertEqual([(p["step"], p["title"]) for p in rows[0]["photos"]], [("right_hand", "Tangan kanan"), ("left_hand", "Tangan kiri")])
		self.assertEqual(rows[1]["photos"][0]["photo"], "/private/files/G2-right_hand.jpg")

	def test_cards_ask_for_the_shift(self):
		self.assertIn("shift", grooming.CARD_FIELDS)

	def test_the_period_defaults_to_today_and_filters_are_passed_on(self):
		grooming.get_grooming_gallery(company="Co", outlet="Out", employee="EMP-1", review_status="Sesuai", search="bud")
		filters = self.calls[0][1]
		self.assertEqual(filters["grooming_date"], ["between", ["2026-10-26", "2026-10-26"]])
		self.assertEqual((filters["company"], filters["outlet"], filters["employee"], filters["review_status"]), ("Co", "Out", "EMP-1", "Sesuai"))
		self.assertEqual(filters["employee_name"], ["like", "%bud%"])

	def test_an_unknown_status_filter_is_ignored_and_a_reversed_range_is_refused(self):
		grooming.get_grooming_gallery(review_status="Whatever")
		self.assertNotIn("review_status", self.calls[0][1])
		with self.assertRaises(frappe.ValidationError):
			grooming.get_grooming_gallery(from_date="2026-10-27", to_date="2026-10-26")

	def test_paging_reports_more_and_caps_the_page_size(self):
		first = grooming.get_grooming_gallery(page_length=1)
		self.assertEqual((len(first["rows"]), first["has_more"]), (1, True))
		last = grooming.get_grooming_gallery(start=1, page_length=1)
		self.assertEqual((len(last["rows"]), last["has_more"]), (1, False))
		grooming.get_grooming_gallery(page_length=5000)
		self.assertEqual(self.calls[-2][2]["page_length"], 101)

	def test_no_cards_means_no_photo_query(self):
		self.cards = []
		self.assertEqual(grooming.get_grooming_gallery(), {"rows": [], "has_more": False})
		self.assertEqual([call[0] for call in self.calls], ["Grooming Check"])


class TestReviewGrooming(unittest.TestCase):
	def setUp(self):
		self.doc = MagicMock()
		self.doc.name = "G1"
		self.doc.reviewed_by = "hr@example.com"
		self.doc.reviewed_on = "2026-10-26 09:00:00"
		for target, kwargs in (("frappe.only_for", {}), ("frappe.get_doc", {"return_value": self.doc})):
			patcher = patch(target, **kwargs)
			self.addCleanup(patcher.stop)
			patcher.start()

	def test_review_saves_through_the_document_so_stamping_and_permissions_apply(self):
		result = grooming.review_grooming("G1", "Tidak Sesuai", "  kuku panjang  ")
		self.assertEqual((self.doc.review_status, self.doc.review_note), ("Tidak Sesuai", "kuku panjang"))
		self.doc.save.assert_called_once_with()
		self.assertEqual(result["review_status"], "Tidak Sesuai")
		self.assertEqual(result["reviewed_by"], "hr@example.com")

	def test_an_empty_note_is_cleared_and_an_invalid_status_is_refused(self):
		grooming.review_grooming("G1", "Sesuai", "   ")
		self.assertIsNone(self.doc.review_note)
		self.doc.save.reset_mock()
		with self.assertRaises(frappe.ValidationError):
			grooming.review_grooming("G1", "Bagus")
		self.doc.save.assert_not_called()
