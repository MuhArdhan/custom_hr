import unittest

from custom_hr.api.payroll_bulk import blocker

KEY = ("Company A", "Hutang Gaji - OA")


class TestPayrollBulkBlocker(unittest.TestCase):
	def test_a_ready_target_has_no_blocker(self):
		self.assertIsNone(blocker(KEY, {("Company A", "Other - OA")}, KEY[1], "Main - OA"))

	def test_each_reason_in_order(self):
		self.assertEqual(blocker(KEY, {KEY}, None, None), "Already created")
		self.assertEqual(blocker(("Company A", None), set(), None, "Main - OA"), "No payroll payable account on the Salary Structure Assignment")
		self.assertEqual(blocker(KEY, set(), KEY[1], None), "The company has no default Cost Center")
