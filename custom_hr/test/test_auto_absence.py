import unittest
from datetime import date, datetime

import frappe

from custom_hr.services.auto_absence import absent_dates, first_full_day

WEEKDAYS = frappe._dict(shift_type="Pagi", enabled=1, days="Senin-Jumat")
NOV_2 = date(2026, 11, 2)  # a Monday


class TestAbsentDates(unittest.TestCase):
	def test_only_scheduled_days_are_absent(self):
		days = absent_dates([WEEKDAYS], NOV_2, date(2026, 11, 8), [], [])
		self.assertEqual(days, [date(2026, 11, d) for d in range(2, 7)])  # Saturday and Sunday have no shift

	def test_holidays_and_covered_days_are_skipped(self):
		days = absent_dates([WEEKDAYS], NOV_2, date(2026, 11, 6), [date(2026, 11, 3)], {date(2026, 11, 4)})
		self.assertEqual(days, [date(2026, 11, 2), date(2026, 11, 5), date(2026, 11, 6)])

	def test_a_disabled_row_schedules_nothing(self):
		self.assertEqual(absent_dates([frappe._dict(WEEKDAYS, enabled=0)], NOV_2, NOV_2, [], []), [])

	def test_mid_day_activation_starts_the_next_day(self):
		self.assertEqual(first_full_day(datetime(2026, 10, 26, 14, 45)), date(2026, 10, 27))
		self.assertEqual(first_full_day(datetime(2026, 10, 26)), date(2026, 10, 26))
