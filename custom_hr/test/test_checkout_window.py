"""HR Settings can keep Check Out closed until some minutes before the shift ends."""

import unittest
from datetime import datetime
from unittest.mock import patch

import frappe

from custom_hr.services import checkout_window as svc

SHIFT_END = datetime(2026, 11, 20, 16, 30)
IN = frappe._dict(shift="Pagi", shift_end=SHIFT_END)


def hr_settings(limit, minutes):
	values = {"batasi_checkout_awal": limit, "checkout_dibuka_menit": minutes}
	return patch.object(svc.frappe.db, "get_single_value", side_effect=lambda doctype, field: values[field])


class TestCheckoutWindow(unittest.TestCase):
	def test_opens_minutes_before_shift_end(self):
		with hr_settings(1, 15):
			self.assertEqual(svc.checkout_opens_at(IN), datetime(2026, 11, 20, 16, 15))

	def test_zero_minutes_opens_at_shift_end(self):
		with hr_settings(1, 0):
			self.assertEqual(svc.checkout_opens_at(IN), SHIFT_END)

	def test_unticked_setting_has_no_limit(self):
		with hr_settings(0, 15):
			self.assertIsNone(svc.checkout_opens_at(IN))

	def test_checkin_without_shift_end_has_no_limit(self):
		with hr_settings(1, 15):
			self.assertIsNone(svc.checkout_opens_at(frappe._dict(shift=None, shift_end=None)))

	def test_early_checkout_is_refused_with_the_opening_time(self):
		with hr_settings(1, 15), self.assertRaises(frappe.ValidationError) as caught:
			svc.validate_checkout_open(IN, datetime(2026, 11, 20, 16, 14))
		self.assertIn("16:15", str(caught.exception))

	def test_checkout_from_opening_time_is_allowed(self):
		with hr_settings(1, 15):
			svc.validate_checkout_open(IN, datetime(2026, 11, 20, 16, 15))
			svc.validate_checkout_open(IN, datetime(2026, 11, 20, 18, 0))  # overtime after the shift


if __name__ == "__main__":
	unittest.main()
