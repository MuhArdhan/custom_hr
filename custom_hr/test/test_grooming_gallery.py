"""Grooming gallery API: filtered cards with their photos, and review straight from the gallery."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.api import grooming


def card(name, status="Menunggu"):
	return frappe._dict(name=name, employee="EMP-1", employee_name="Budi", company="Co", outlet=None, grooming_date="2026-10-26", submitted_at="2026-10-26 08:00:00", review_status=status, review_note=None)


def photo(parent, step, idx, detection_boxes=None):
	return frappe._dict(parent=parent, step=step, photo=f"/private/files/{parent}-{step}.jpg", detection_boxes=detection_boxes, idx=idx)


class TestGroomingGallery(unittest.TestCase):
	def setUp(self):
		self.cards = [card("G1"), card("G2", "Sesuai")]
		self.photos = [photo("G1", "left_hand", 2), photo("G1", "right_hand", 1), photo("G2", "right_hand", 1)]
		self.calls = []
		self.settings = {"enable_box": True}
		self.only_for = self.patch("custom_hr.api.grooming.require_page_access")
		self.patch("frappe.get_all", side_effect=self.get_all)
		self.patch("frappe.db.count", side_effect=lambda doctype, filters: len(self.cards))
		self.patch("custom_hr.api.grooming.nowdate", return_value="2026-10-26")
		self.patch("custom_hr.api.grooming.get_grooming_settings", side_effect=lambda: dict(self.settings))

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

	def test_only_roles_of_the_page_may_open_the_gallery_or_review(self):
		self.only_for.side_effect = frappe.PermissionError("nope")
		with self.assertRaises(frappe.PermissionError):
			grooming.get_grooming_gallery()
		with self.assertRaises(frappe.PermissionError):
			grooming.review_grooming("G1", "Sesuai")
		self.only_for.assert_called_with("grooming-gallery")

	def test_cards_carry_their_photos_in_step_order_with_titles(self):
		rows = grooming.get_grooming_gallery()["rows"]
		self.assertEqual([r["name"] for r in rows], ["G1", "G2"])
		self.assertEqual([(p["step"], p["title"]) for p in rows[0]["photos"]], [("right_hand", "Jari tangan kanan, celemek dan topi"), ("left_hand", "Jari tangan kiri, celemek dan topi")])
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

	def test_paging_reports_the_total_and_caps_the_page_size(self):
		first = grooming.get_grooming_gallery(page_length=1)
		self.assertEqual((len(first["rows"]), first["has_more"], first["total"]), (1, True, 2))
		last = grooming.get_grooming_gallery(start=1, page_length=1)
		self.assertEqual((len(last["rows"]), last["has_more"], last["total"]), (1, False, 2))
		grooming.get_grooming_gallery(page_length=5000)
		self.assertEqual(self.calls[-2][2]["page_length"], 501)

	def test_no_cards_means_no_photo_query(self):
		self.cards = []
		self.assertEqual(grooming.get_grooming_gallery(), {"rows": [], "has_more": False, "total": 0})
		self.assertEqual([call[0] for call in self.calls], ["Grooming Check"])

	def test_gallery_returns_boxes_only_when_enable_box_is_on(self):
		box_json = '[{"label":"Topi","ok":true,"x":0.1,"y":0.2,"w":0.3,"h":0.4}]'
		self.photos = [photo("G1", "right_hand", 1, detection_boxes=box_json)]
		rows_on = grooming.get_grooming_gallery()["rows"]
		self.assertEqual(rows_on[0]["photos"][0]["boxes"][0]["label"], "Topi")

		self.settings["enable_box"] = False
		rows_off = grooming.get_grooming_gallery()["rows"]
		self.assertEqual(rows_off[0]["photos"][0]["boxes"], [])


class TestReviewGrooming(unittest.TestCase):
	def setUp(self):
		self.doc = MagicMock()
		self.doc.name = "G1"
		self.doc.reviewed_by = "hr@example.com"
		self.doc.reviewed_on = "2026-10-26 09:00:00"
		for target, kwargs in (("custom_hr.api.grooming.require_page_access", {}), ("frappe.get_doc", {"return_value": self.doc})):
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


class TestRequirePageAccess(unittest.TestCase):
	def test_follows_the_page_roles(self):
		from custom_hr.api import require_page_access

		page = MagicMock()
		with patch("frappe.get_doc", return_value=page) as get_doc:
			page.is_permitted.return_value = True
			require_page_access("grooming-gallery")
			get_doc.assert_called_with("Page", "grooming-gallery")
			page.is_permitted.return_value = None
			with self.assertRaises(frappe.PermissionError):
				require_page_access("grooming-gallery")


class TestRecheckGrooming(unittest.TestCase):
	def setUp(self):
		self.doc = MagicMock()
		self.doc.name = "G1"
		self.doc.review_status = "Menunggu"
		self.doc.reviewed_by = None
		self.doc.reviewed_on = "2026-10-26 09:00:00"
		for target, kwargs in (
			("custom_hr.api.grooming.require_page_access", {}),
			("frappe.get_doc", {"return_value": self.doc}),
			("custom_hr.api.grooming.read_doc_photos_bytes", {"return_value": {"right_hand": b"1", "left_hand": b"2", "trousers": b"3", "footwear": b"4"}}),
			("custom_hr.api.grooming.get_grooming_settings", {"return_value": {"enable_auto_review": False, "hat_threshold": 0.3, "apron_threshold": 0.5, "shoes_threshold": 0.4, "jeans_threshold": 0.5, "reject_crocs": False, "crocs_threshold": 0.5}}),
			("custom_hr.api.grooming.classify_grooming_photos", {"return_value": {"review_status": "Tidak Sesuai", "review_note": "Auto-review: Tidak sesuai"}}),
		):
			patcher = patch(target, **kwargs)
			self.addCleanup(patcher.stop)
			patcher.start()

	def test_recheck_runs_classifier_and_saves_with_auto_review_flag(self):
		result = grooming.recheck_grooming("G1")
		self.assertTrue(self.doc.flags.auto_review)
		self.doc.save.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(result["review_status"], "Tidak Sesuai")
		self.assertEqual(result["review_note"], "Auto-review: Tidak sesuai")


class TestGroomingKukuGallery(unittest.TestCase):
	def setUp(self):
		self.cards = [frappe._dict(name="G1", employee="EMP-1", employee_name="Budi", company="Co", outlet=None, grooming_date="2026-10-26", submitted_at="2026-10-26 08:00:00", nail_review_status="Menunggu", nail_review_note=None)]
		self.photos = [
			photo("G1", "right_hand", 1, detection_boxes='[{"label":"Topi","score":0.8}]'),
			photo("G1", "left_hand", 2),
			photo("G1", "trousers", 3),
			photo("G1", "footwear", 4),
		]
		self.calls = []
		self.only_for = patch("custom_hr.api.grooming.require_page_access")
		self.addCleanup(self.only_for.stop)
		self.only_for = self.only_for.start()
		for target, kwargs in (
			("frappe.get_all", {"side_effect": self.get_all}),
			("frappe.db.count", {"side_effect": lambda doctype, filters: len(self.cards)}),
			("custom_hr.api.grooming.nowdate", {"return_value": "2026-10-26"}),
		):
			p = patch(target, **kwargs)
			self.addCleanup(p.stop)
			p.start()

	def get_all(self, doctype, filters=None, fields=None, **kwargs):
		self.calls.append((doctype, dict(filters or {}), kwargs))
		if doctype == "Grooming Check":
			return self.cards
		allowed = set(filters["step"][1])
		return [p for p in sorted(self.photos, key=lambda p: p.idx) if p.step in allowed]

	def test_kuku_gallery_fetches_only_hand_photos_and_uses_nail_review_status(self):
		res = grooming.get_grooming_kuku_gallery(review_status="Menunggu")
		self.only_for.assert_called_with("grooming-kuku-gallery")
		self.assertEqual(self.calls[0][1]["nail_review_status"], "Menunggu")
		self.assertEqual([p["step"] for p in res["rows"][0]["photos"]], ["right_hand", "left_hand"])
		self.assertNotIn("boxes", res["rows"][0]["photos"][0])

	def test_review_grooming_kuku_updates_only_nail_review_fields(self):
		doc = MagicMock()
		doc.name = "G1"
		doc.nail_reviewed_by = "hr@example.com"
		doc.nail_reviewed_on = "2026-10-26 10:00:00"
		with patch("custom_hr.api.grooming.require_page_access") as access, patch("frappe.get_doc", return_value=doc):
			result = grooming.review_grooming_kuku("G1", "Tidak Sesuai", "  Kuku panjang  ")
		access.assert_called_with("grooming-kuku-gallery")
		self.assertEqual((doc.nail_review_status, doc.nail_review_note), ("Tidak Sesuai", "Kuku panjang"))
		doc.save.assert_called_once_with()
		self.assertEqual(result["nail_review_status"], "Tidak Sesuai")
		self.assertEqual(result["nail_reviewed_by"], "hr@example.com")
