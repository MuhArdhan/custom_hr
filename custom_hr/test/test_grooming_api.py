"""Grooming API: the employee and date are the server's, all photos or nothing, once a day."""

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
		self.checkin = frappe._dict(name="IN-1", shift="Shift Pagi")
		self.history = []
		self.photos = []
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
		self.get_value = self.patch("frappe.db.get_value", side_effect=lambda doctype, *a, **k: self.checkin if doctype == "Employee Checkin" else self.record)
		self.patch("frappe.get_all", side_effect=lambda doctype, *a, **k: self.photos if doctype == "Grooming Photo" else self.history)

	def patch(self, name, **kwargs):
		target = name if name.startswith("frappe.") else f"custom_hr.api.grooming.{name}"
		patcher = patch(target, **kwargs)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def test_status_lists_the_steps_and_not_submitted(self):
		status = grooming.get_grooming_status()
		self.assertEqual([step["key"] for step in status["steps"]], KEYS)
		self.assertEqual((status["date"], status["submitted"], status["review_status"]), ("2026-10-26", False, None))

	def test_status_reports_whether_the_employee_checked_in_and_the_shift(self):
		status = grooming.get_grooming_status()
		self.assertEqual((status["checked_in"], status["shift"]), (True, "Shift Pagi"))
		self.checkin = None
		status = grooming.get_grooming_status()
		self.assertEqual((status["checked_in"], status["shift"]), (False, None))

	def test_the_checkin_lookup_uses_the_server_date_and_the_latest_in(self):
		grooming.get_grooming_status()
		call = next(c for c in self.get_value.call_args_list if c.args[0] == "Employee Checkin")
		filters = call.args[1]
		self.assertEqual((filters["employee"], filters["log_type"], filters["time"]), ("EMP-1", "IN", ["between", ["2026-10-26 00:00:00", "2026-10-26 23:59:59"]]))
		self.assertEqual(call.kwargs["order_by"], "time desc")

	def test_status_includes_the_history_newest_first(self):
		self.history = [frappe._dict(name="G2", grooming_date="2026-10-26", shift="Shift Pagi", review_status="Sesuai", review_note=None)]
		history = grooming.get_grooming_status()["history"]
		self.assertEqual([(h["name"], h["date"], h["shift"], h["review_status"]) for h in history], [("G2", "2026-10-26", "Shift Pagi", "Sesuai")])

	def test_detail_returns_my_record_with_its_photos_in_step_order_and_titles(self):
		self.record = frappe._dict(name="G1", employee="EMP-1", grooming_date="2026-10-26", shift="Shift Pagi", submitted_at="2026-10-26 08:00:00", review_status="Tidak Sesuai", review_note="kuku panjang", reviewed_on="2026-10-26 09:00:00")
		self.photos = [frappe._dict(step=key, photo=f"/private/files/{key}.jpg") for key in KEYS]
		detail = grooming.get_grooming_detail("G1")
		self.assertEqual((detail["name"], detail["shift"], detail["review_status"], detail["review_note"]), ("G1", "Shift Pagi", "Tidak Sesuai", "kuku panjang"))
		self.assertEqual([(p["step"], p["title"]) for p in detail["photos"]][:2], [("right_hand", "Tangan kanan"), ("left_hand", "Tangan kiri")])
		self.assertEqual(len(detail["photos"]), len(KEYS))

	def test_detail_refuses_another_employees_or_a_missing_record_with_the_same_message(self):
		self.record = frappe._dict(name="G1", employee="EMP-2", grooming_date="2026-10-26")
		with self.assertRaises(frappe.PermissionError) as other:
			grooming.get_grooming_detail("G1")
		self.record = None
		with self.assertRaises(frappe.PermissionError) as missing:
			grooming.get_grooming_detail("NOPE")
		self.assertEqual(str(other.exception), str(missing.exception))

	def test_submit_requires_a_checkin_today_and_writes_nothing_without_one(self):
		self.checkin = None
		with self.assertRaisesRegex(frappe.ValidationError, "check in"):
			grooming.submit_grooming([JPEG] * len(KEYS))
		self.writer.assert_not_called()
		self.save.assert_not_called()

	def test_submit_stores_the_shift_and_checkin_of_the_day(self):
		grooming.submit_grooming([JPEG] * len(KEYS))
		values = self.writer.call_args.args[0]
		self.assertEqual((values["shift"], values["checkin"]), ("Shift Pagi", "IN-1"))

	def test_an_off_shift_checkin_still_allows_grooming_without_a_shift(self):
		self.checkin = frappe._dict(name="IN-2", shift=None)
		grooming.submit_grooming([JPEG] * len(KEYS))
		self.assertIsNone(self.writer.call_args.args[0]["shift"])

	def test_status_shows_todays_review_result(self):
		self.record = frappe._dict(name="GRM-1", review_status="Tidak Sesuai", review_note="kuku panjang")
		status = grooming.get_grooming_status()
		self.assertEqual((status["submitted"], status["review_status"], status["review_note"]), (True, "Tidak Sesuai", "kuku panjang"))

	def test_submit_creates_one_record_for_the_session_employee(self):
		result = grooming.submit_grooming(([JPEG, PNG] * len(KEYS))[:len(KEYS)])
		values = self.writer.call_args.args[0]
		self.assertEqual((values["doctype"], values["employee"], values["grooming_date"], values["submitted_at"]), ("Grooming Check", "EMP-1", "2026-10-26", NOW))
		self.assertEqual([row["step"] for row in values["photos"]], KEYS)
		self.doc.insert.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(result, {"name": "GRM-EMP-1-2026-10-26", "review_status": "Menunggu"})

	def test_payload_cannot_name_another_employee(self):
		with self.assertRaises(TypeError):
			grooming.submit_grooming([JPEG] * len(KEYS), employee="EMP-2")

	def test_user_without_an_active_employee_is_refused(self):
		self.employee.side_effect = frappe.ValidationError("no employee")
		with self.assertRaises(frappe.ValidationError):
			grooming.submit_grooming([JPEG] * len(KEYS))
		self.writer.assert_not_called()

	def test_too_few_or_too_many_photos_are_refused_and_nothing_is_written(self):
		for count in (0, len(KEYS) - 1, len(KEYS) + 1):
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
			grooming.submit_grooming([JPEG] * len(KEYS))
		self.writer.assert_not_called()

	def test_a_simultaneous_duplicate_is_reported_as_already_sent(self):
		self.doc.insert.side_effect = frappe.DuplicateEntryError("Grooming Check", self.doc.name, Exception("dup"))
		with self.assertRaisesRegex(frappe.ValidationError, "sudah"):
			grooming.submit_grooming([JPEG] * len(KEYS))
		self.save.assert_not_called()

	def test_photos_are_saved_in_step_order_on_the_record(self):
		grooming.submit_grooming([JPEG] * len(KEYS))
		self.assertEqual([call.args[1:3] for call in self.save.call_args_list], [("Grooming Check", self.doc.name)] * len(KEYS))
		self.assertEqual([call.args[3] for call in self.save.call_args_list], [f"grooming-{self.doc.name}-{key}" for key in KEYS])
		self.assertEqual([call.args[1] for call in self.set_value.call_args_list], [f"ROW-{i}" for i in range(len(KEYS))])
		self.assertEqual([call.args[3] for call in self.set_value.call_args_list], [f"/private/files/grooming-{self.doc.name}-{key}.jpg" for key in KEYS])
