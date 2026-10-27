"""Grooming Check: five photos in step order, review stamping, and an immutable submission."""

import unittest

import frappe

from custom_hr.services.grooming import GROOMING_STEPS

KEYS = ["right_hand", "left_hand", "cap", "trousers", "footwear"]


def check(keys=None, **values):
	doc = frappe.new_doc("Grooming Check")
	doc.update({"employee": "EMP-1", "grooming_date": "2026-10-26", "submitted_at": "2026-10-26 08:00:00", **values})
	for key in KEYS if keys is None else keys:
		doc.append("photos", {"step": key, "photo": f"/private/files/{key}.jpg", "taken_at": "2026-10-26 08:00:00"})
	return doc


class TestGroomingSteps(unittest.TestCase):
	def test_steps_are_the_five_in_order(self):
		self.assertEqual([step["key"] for step in GROOMING_STEPS], KEYS)
		for step in GROOMING_STEPS:
			self.assertTrue(step["title"] and step["hint"])


class TestGroomingCheck(unittest.TestCase):
	def test_review_status_options_are_real_choices_and_the_default_is_valid(self):
		field = frappe.get_meta("Grooming Check").get_field("review_status")
		self.assertEqual(field.options.split("\n"), ["Menunggu", "Sesuai", "Tidak Sesuai"])
		self.assertEqual(field.default, "Menunggu")

	def test_a_new_record_passes_the_native_field_checks(self):
		doc = check()
		doc.review_status = "Menunggu"
		doc._validate_selects()
		doc._validate_data_fields()

	def test_exactly_five_photos_in_step_order_are_required(self):
		check().validate_photos()
		for keys in (KEYS[:4], KEYS + ["footwear"], list(reversed(KEYS)), [], KEYS[:2] + KEYS[3:] + ["cap"]):
			with self.subTest(keys=keys), self.assertRaises(frappe.ValidationError):
				check(keys).validate_photos()

	def test_a_photo_row_without_a_photo_is_refused(self):
		doc = check()
		doc.photos[2].photo = None
		with self.assertRaises(frappe.ValidationError):
			doc.validate_photos()

	def test_review_stamps_reviewer_and_time_and_clears_on_reset(self):
		doc = check(review_status="Sesuai")
		doc.stamp_review(None)
		self.assertEqual(doc.reviewed_by, frappe.session.user)
		self.assertTrue(doc.reviewed_on)
		reviewed = check(review_status="Sesuai")
		reviewed.stamp_review(None)
		reset = check(review_status="Menunggu", reviewed_by=reviewed.reviewed_by, reviewed_on=reviewed.reviewed_on)
		reset.stamp_review(reviewed)
		self.assertFalse(reset.reviewed_by or reset.reviewed_on)

	def test_a_stamped_review_is_kept_when_the_status_does_not_change(self):
		before = check(review_status="Tidak Sesuai", reviewed_by="first@example.com", reviewed_on="2026-10-26 09:00:00")
		after = check(review_status="Tidak Sesuai", reviewed_by="first@example.com", reviewed_on="2026-10-26 09:00:00", review_note="kuku panjang")
		after.stamp_review(before)
		self.assertEqual(after.reviewed_by, "first@example.com")

	def test_changing_employee_date_or_photos_after_creation_is_refused(self):
		before = check()
		for change in (dict(employee="EMP-2"), dict(grooming_date="2026-10-27"), dict(submitted_at="2026-10-26 09:00:00")):
			with self.subTest(change=change), self.assertRaises(frappe.ValidationError):
				check(**change).validate_unchanged(before)
		swapped = check()
		swapped.photos[0].photo = "/private/files/other.jpg"
		with self.assertRaises(frappe.ValidationError):
			swapped.validate_unchanged(before)

	def test_review_note_can_change_after_creation(self):
		check(review_note="kuku panjang", review_status="Tidak Sesuai").validate_unchanged(check())
