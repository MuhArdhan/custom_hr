"""Grooming Check: one photo per step in order, review stamping, and an immutable submission."""

import unittest

import frappe

from custom_hr.services.grooming import GROOMING_STEPS, STEP_TITLES

KEYS = ["right_hand", "left_hand", "trousers", "footwear"]
OLD_KEYS = ["right_hand", "left_hand", "cap", "trousers", "footwear"]  # before the cap step was dropped


def check(keys=None, **values):
	doc = frappe.new_doc("Grooming Check")
	doc.update({"employee": "EMP-1", "grooming_date": "2026-10-26", "submitted_at": "2026-10-26 08:00:00", **values})
	for key in KEYS if keys is None else keys:
		doc.append("photos", {"step": key, "photo": f"/private/files/{key}.jpg", "taken_at": "2026-10-26 08:00:00"})
	return doc


class TestGroomingSteps(unittest.TestCase):
	def test_steps_are_the_four_in_order(self):
		self.assertEqual([step["key"] for step in GROOMING_STEPS], KEYS)
		for step in GROOMING_STEPS:
			self.assertTrue(step["title"] and step["hint"])

	def test_older_cap_photos_keep_their_title(self):
		self.assertEqual(STEP_TITLES["cap"], "Topi")
		self.assertTrue(all(STEP_TITLES[key] for key in KEYS))


class TestGroomingCheck(unittest.TestCase):
	def test_review_status_options_are_real_choices_and_the_default_is_valid(self):
		field = frappe.get_meta("Grooming Check").get_field("review_status")
		self.assertEqual(field.options.split("\n"), ["Menunggu", "Sesuai", "Tidak Sesuai"])
		self.assertEqual(field.default, "Menunggu")

	def test_the_shift_is_shown_in_the_list_and_can_be_filtered(self):
		field = frappe.get_meta("Grooming Check").get_field("shift")
		self.assertEqual((field.fieldtype, field.options, field.read_only), ("Link", "Shift Type", 1))
		self.assertTrue(field.in_list_view and field.in_standard_filter)
		self.assertEqual(frappe.get_meta("Grooming Check").get_field("checkin").options, "Employee Checkin")

	def test_a_new_record_passes_the_native_field_checks(self):
		doc = check()
		doc.review_status = "Menunggu"
		doc._validate_selects()
		doc._validate_data_fields()

	def test_exactly_one_photo_per_step_in_order_is_required(self):
		check().validate_photos()
		for keys in (KEYS[:3], KEYS + ["footwear"], list(reversed(KEYS)), [], OLD_KEYS):
			with self.subTest(keys=keys), self.assertRaises(frappe.ValidationError):
				check(keys).validate_photos()

	def test_an_older_record_with_a_cap_photo_can_still_be_reviewed(self):
		before = check(OLD_KEYS)
		after = check(OLD_KEYS, review_status="Sesuai")
		after.is_new = lambda: False
		after.get_doc_before_save = lambda: before
		after.validate()
		self.assertEqual(after.reviewed_by, frappe.session.user)

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
		for change in (dict(shift="Shift Malam"), dict(checkin="IN-9")):
			with self.subTest(change=change), self.assertRaises(frappe.ValidationError):
				check(**change).validate_unchanged(check(shift="Shift Pagi", checkin="IN-1"))
		swapped = check()
		swapped.photos[0].photo = "/private/files/other.jpg"
		with self.assertRaises(frappe.ValidationError):
			swapped.validate_unchanged(before)

	def test_review_note_can_change_after_creation(self):
		check(review_note="kuku panjang", review_status="Tidak Sesuai").validate_unchanged(check())
