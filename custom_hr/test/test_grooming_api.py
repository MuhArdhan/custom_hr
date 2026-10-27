"""Grooming API: the employee and date are the server's, all five photos or nothing, once a day."""

import base64
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.api import grooming
from custom_hr.services.grooming import GROOMING_STEPS, MAX_IMAGE_BYTES, check_image

NOW = datetime(2026, 10, 26, 8, 30)
JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"0" * 50).decode()
PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 50).decode()
KEYS = [step["key"] for step in GROOMING_STEPS]


class TestCheckImage(unittest.TestCase):
	def test_check_image_accepts_jpeg_and_png_only(self):
		self.assertTrue(check_image(JPEG).startswith(b"\xff\xd8\xff"))
		self.assertTrue(check_image(PNG).startswith(b"\x89PNG"))
		gif = "data:image/gif;base64," + base64.b64encode(b"GIF89a" + b"0" * 20).decode()
		wrong_magic = "data:image/png;base64," + base64.b64encode(b"\xff\xd8\xff" + b"0" * 20).decode()
		for value in (gif, wrong_magic, "data:image/jpeg;base64,@@@not-base64", "https://example.com/a.jpg", "", None, 123, "data:image/jpeg;base64,"):
			with self.subTest(value=str(value)[:30]), self.assertRaises(frappe.ValidationError):
				check_image(value)

	def test_an_oversized_image_is_refused(self):
		big = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"0" * (MAX_IMAGE_BYTES + 1)).decode()
		with self.assertRaises(frappe.ValidationError):
			check_image(big)


class TestGroomingApi(unittest.TestCase):
	def setUp(self):
		self.record = None
		self.doc = MagicMock()
		self.doc.name = "GRM-EMP-1-2026-10-26"
		self.doc.photos = [MagicMock(name=f"row-{key}", step=key) for key in KEYS]
		for index, row in enumerate(self.doc.photos):
			row.name = f"ROW-{index}"
		self.employee = self.patch("get_current_employee", return_value="EMP-1")
		self.patch("nowdate", return_value="2026-10-26")
		self.patch("now_datetime", return_value=NOW)
		self.writer = self.patch("frappe.get_doc", return_value=self.doc)
		self.save = self.patch("_save_photo_data_url", side_effect=lambda data, doctype, name, filename: f"/private/files/{filename}.jpg")
		self.exists = self.patch("frappe.db.exists", return_value=None)
		self.set_value = self.patch("frappe.db.set_value")
		self.patch("frappe.db.get_value", side_effect=lambda *a, **k: self.record)

	def patch(self, name, **kwargs):
		target = name if name.startswith("frappe.") else f"custom_hr.api.grooming.{name}"
		patcher = patch(target, **kwargs)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def test_status_lists_the_five_steps_and_not_submitted(self):
		status = grooming.get_grooming_status()
		self.assertEqual([step["key"] for step in status["steps"]], KEYS)
		self.assertEqual((status["date"], status["submitted"], status["review_status"]), ("2026-10-26", False, None))

	def test_status_shows_todays_review_result(self):
		self.record = frappe._dict(name="GRM-1", review_status="Tidak Sesuai", review_note="kuku panjang")
		status = grooming.get_grooming_status()
		self.assertEqual((status["submitted"], status["review_status"], status["review_note"]), (True, "Tidak Sesuai", "kuku panjang"))

	def test_submit_creates_one_record_for_the_session_employee(self):
		result = grooming.submit_grooming([JPEG, PNG, JPEG, PNG, JPEG])
		values = self.writer.call_args.args[0]
		self.assertEqual((values["doctype"], values["employee"], values["grooming_date"], values["submitted_at"]), ("Grooming Check", "EMP-1", "2026-10-26", NOW))
		self.assertEqual([row["step"] for row in values["photos"]], KEYS)
		self.doc.insert.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(result, {"name": "GRM-EMP-1-2026-10-26", "review_status": "Menunggu"})

	def test_payload_cannot_name_another_employee(self):
		with self.assertRaises(TypeError):
			grooming.submit_grooming([JPEG] * 5, employee="EMP-2")

	def test_user_without_an_active_employee_is_refused(self):
		self.employee.side_effect = frappe.ValidationError("no employee")
		with self.assertRaises(frappe.ValidationError):
			grooming.submit_grooming([JPEG] * 5)
		self.writer.assert_not_called()

	def test_four_or_six_photos_are_refused_and_nothing_is_written(self):
		for count in (0, 4, 6):
			with self.subTest(count=count), self.assertRaises(frappe.ValidationError):
				grooming.submit_grooming([JPEG] * count)
		self.writer.assert_not_called()
		self.save.assert_not_called()

	def test_a_non_image_or_oversized_photo_is_refused_before_any_write(self):
		for bad in ("not an image", "data:image/gif;base64,R0lGODlh", None):
			with self.subTest(bad=bad), self.assertRaises(frappe.ValidationError):
				grooming.submit_grooming([JPEG] * 4 + [bad])
		self.writer.assert_not_called()
		self.save.assert_not_called()

	def test_second_submission_the_same_day_is_refused_even_after_tidak_sesuai(self):
		self.exists.return_value = "GRM-EMP-1-2026-10-26"
		self.record = frappe._dict(name="GRM-1", review_status="Tidak Sesuai")
		with self.assertRaisesRegex(frappe.ValidationError, "sudah"):
			grooming.submit_grooming([JPEG] * 5)
		self.writer.assert_not_called()

	def test_a_simultaneous_duplicate_is_reported_as_already_sent(self):
		self.doc.insert.side_effect = frappe.DuplicateEntryError("Grooming Check", self.doc.name, Exception("dup"))
		with self.assertRaisesRegex(frappe.ValidationError, "sudah"):
			grooming.submit_grooming([JPEG] * 5)
		self.save.assert_not_called()

	def test_photos_are_saved_in_step_order_on_the_record(self):
		grooming.submit_grooming([JPEG] * 5)
		self.assertEqual([call.args[1:3] for call in self.save.call_args_list], [("Grooming Check", self.doc.name)] * 5)
		self.assertEqual([call.args[3] for call in self.save.call_args_list], [f"grooming-{self.doc.name}-{key}" for key in KEYS])
		self.assertEqual([call.args[1] for call in self.set_value.call_args_list], [f"ROW-{i}" for i in range(5)])
		self.assertEqual([call.args[3] for call in self.set_value.call_args_list], [f"/private/files/grooming-{self.doc.name}-{key}.jpg" for key in KEYS])
