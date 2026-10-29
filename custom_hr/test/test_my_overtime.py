"""Employee overtime from the HRMS app: own name only, today up to a week ahead, cancel only while undecided."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from custom_hr.api import my_overtime
from custom_hr.services.overtime_approval import SELF_REQUEST_TOKEN

USER = "crew@example.com"


def request(status="Menunggu Leader", employees=("EMP-1",), requested_by=USER, approval_state=None):
	doc = MagicMock()
	doc.name, doc.status, doc.requested_by = "LEMBUR-1", status, requested_by
	doc.date, doc.start_time, doc.end_time, doc.planned_hours, doc.reason = "2026-10-26", "17:00:00", "19:00:00", 2, "stok opname"
	doc.employees = [frappe._dict(employee=employee, approval_state=approval_state) for employee in employees]
	return doc


class TestMyOvertimeApi(unittest.TestCase):
	def setUp(self):
		self.doc = request()
		self.patch("get_current_employee", return_value="EMP-1")
		self.patch("nowdate", return_value="2026-10-26")
		self.writer = self.patch("frappe.get_doc", return_value=self.doc)
		self.exists = self.patch("frappe.db.exists", return_value=True)
		self.patch("frappe.db.get_value", side_effect=lambda doctype, *a, **k: frappe._dict(outlet="OUT-1", company="ROPI") if doctype == "Employee" else "Menunggu Leader")
		self.delete = self.patch("frappe.delete_doc")
		self.patch("frappe.session", new=frappe._dict(user=USER))

	def patch(self, name, **kwargs):
		target = name if name.startswith("frappe.") else f"custom_hr.api.my_overtime.{name}"
		patcher = patch(target, **kwargs)
		self.addCleanup(patcher.stop)
		return patcher.start()

	def test_the_request_is_always_for_today_and_no_date_can_be_sent(self):
		my_overtime.submit_my_overtime("17:00", "19:00", "stok opname")
		self.assertEqual(self.writer.call_args.args[0]["date"], "2026-10-26")  # the server date
		with self.assertRaises(TypeError):
			my_overtime.submit_my_overtime("17:00", "19:00", "stok opname", date="2026-11-02")
		with patch("frappe.get_all", return_value=[]):
			self.assertEqual(my_overtime.get_my_overtime()["date"], "2026-10-26")

	def test_a_reason_is_required(self):
		for reason in ("", "   ", None):
			with self.subTest(reason=reason), self.assertRaises(frappe.ValidationError):
				my_overtime.submit_my_overtime("17:00", "19:00", reason)
		self.writer.assert_not_called()

	def test_the_request_holds_only_the_session_employee_and_runs_the_normal_rules(self):
		my_overtime.submit_my_overtime("17:00", "19:00", " stok opname ")
		values = self.writer.call_args.args[0]
		self.assertEqual(values["employees"], [{"employee": "EMP-1"}])
		self.assertEqual((values["outlet"], values["company"], values["requested_by"], values["reason"]), ("OUT-1", "ROPI", USER, "stok opname"))
		self.assertEqual((values["doctype"], values["overtime_type"], values["date"]), ("Overtime Request", "Lembur", "2026-10-26"))
		self.assertIs(self.doc.flags.overtime_self_request, SELF_REQUEST_TOKEN)
		self.doc.insert.assert_called_once_with(ignore_permissions=True)

	def test_the_chosen_overtime_type_is_used_and_an_unknown_one_is_refused(self):
		self.exists.side_effect = lambda doctype, name=None: doctype != "Overtime Type" or name in ("Lembur", "Lembur Libur")
		my_overtime.submit_my_overtime("17:00", "19:00", "stok opname", overtime_type="Lembur Libur")
		self.assertEqual(self.writer.call_args.args[0]["overtime_type"], "Lembur Libur")
		my_overtime.submit_my_overtime("17:00", "19:00", "stok opname")
		self.assertEqual(self.writer.call_args.args[0]["overtime_type"], "Lembur")
		for forged in ("Lembur Palsu", ["Lembur"]):
			with self.subTest(forged=forged), self.assertRaises(frappe.ValidationError):
				my_overtime.submit_my_overtime("17:00", "19:00", "stok opname", overtime_type=forged)
		self.assertEqual(self.writer.call_count, 2)

	def test_the_form_lists_the_types_with_their_cap_and_lembur_preselected(self):
		types = [frappe._dict(name="Lembur", max_hours=4.0), frappe._dict(name="Lembur Libur", max_hours=None)]
		with patch("frappe.get_all", side_effect=lambda doctype, **k: types if doctype == "Overtime Type" else []):
			state = my_overtime.get_my_overtime()
		self.assertEqual(state["overtime_types"], [{"name": "Lembur", "max_hours": 4.0}, {"name": "Lembur Libur", "max_hours": 0}])
		self.assertEqual(state["default_overtime_type"], "Lembur")

	def test_history_names_who_each_pending_stage_waits_for(self):
		names = {"leader@example.com": "Budi Leader", "spv@example.com": None}
		doc = request(status="Menunggu Leader")
		doc.get = lambda field: {"approver_1": "leader@example.com", "approver_2": "spv@example.com"}.get(field)
		with patch("frappe.db.get_value", side_effect=lambda doctype, name, field: names[name]):
			self.assertEqual(my_overtime.waiting_for(doc, "Menunggu Leader"), "Budi Leader")
			self.assertEqual(my_overtime.waiting_for(doc, "Menunggu SPV"), "spv@example.com")  # no full name: the user id
		self.assertEqual(my_overtime.waiting_for(doc, "Menunggu HRD"), "HRD")
		self.assertIsNone(my_overtime.waiting_for(doc, "Disetujui"))
		doc.get = lambda field: None  # outlet without a leader
		self.assertIsNone(my_overtime.waiting_for(doc, "Menunggu Leader"))

	def test_own_pending_request_can_be_cancelled(self):
		for status in ("Menunggu Leader", "Menunggu SPV", "Menunggu HRD"):
			self.doc.status = status
			my_overtime.cancel_my_overtime("LEMBUR-1")
		self.writer.return_value = request(status="Menunggu SPV", approval_state="Menunggu SPV")  # leader approved in the Working Calendar
		my_overtime.cancel_my_overtime("LEMBUR-1")
		self.assertEqual(self.delete.call_count, 4)

	def test_a_decided_foreign_or_leader_made_request_cannot_be_cancelled(self):
		cases = {
			"approved": request(status="Disetujui"),
			"rejected": request(status="Ditolak"),
			"rejected in the Working Calendar": request(status="Menunggu Leader", approval_state="Ditolak"),
			"made by the leader": request(requested_by="leader@example.com"),
			"for the crew": request(employees=("EMP-1", "EMP-2")),
		}
		for case, doc in cases.items():
			self.writer.return_value = doc
			with self.subTest(case=case), self.assertRaises(frappe.ValidationError):
				my_overtime.cancel_my_overtime("LEMBUR-1")
		self.writer.return_value = request(employees=("EMP-2",))
		with self.assertRaises(frappe.PermissionError):
			my_overtime.cancel_my_overtime("LEMBUR-1")
		self.delete.assert_not_called()


class TestSelfRequest(unittest.TestCase):
	def doc(self, employees, token=None):
		doc = frappe.new_doc("Overtime Request")
		for employee in employees:
			doc.append("employees", {"employee": employee})
		if token:
			doc.flags.overtime_self_request = token
		return doc

	def test_only_the_server_token_and_the_own_name_make_a_self_request(self):
		own = self.doc(["EMP-1"], SELF_REQUEST_TOKEN)
		others = [self.doc(["EMP-1"]), self.doc(["EMP-1"], object()), self.doc(["EMP-2"], SELF_REQUEST_TOKEN), self.doc(["EMP-1", "EMP-2"], SELF_REQUEST_TOKEN)]
		with patch("frappe.db.get_value", return_value="EMP-1"):
			self.assertTrue(own.is_self_request())
			for doc in others:
				self.assertFalse(doc.is_self_request())
		with patch("frappe.db.get_value", return_value=None):  # the user has no Employee record
			self.assertFalse(own.is_self_request())


class TestOvertimeCap(unittest.TestCase):
	def request(self, overtime_type, start, end):
		doc = frappe.new_doc("Overtime Request")
		doc.update({"overtime_type": overtime_type, "start_time": start, "end_time": end})
		return doc

	def test_the_cap_comes_from_the_overtime_type_and_zero_means_none(self):
		caps = {"Lembur": 4, "Lembur Libur": 8, "Tanpa Batas": 0}
		fits = [self.request("Lembur", "17:00:00", "21:00:00"), self.request("Lembur Libur", "08:00:00", "16:00:00")]
		too_long = {"maksimal 4 jam": self.request("Lembur", "17:00:00", "22:00:00"), "maksimal 8 jam": self.request("Lembur Libur", "08:00:00", "17:00:00")}
		uncapped = self.request("Tanpa Batas", "08:00:00", "20:00:00")
		with patch("frappe.db.get_value", side_effect=lambda doctype, name, field: caps[name]):
			for doc in fits:
				doc.validate_times()
			for message, doc in too_long.items():
				with self.subTest(message=message), self.assertRaisesRegex(frappe.ValidationError, message):
					doc.validate_times()
			uncapped.validate_times()
		self.assertEqual(uncapped.planned_hours, 12)


class TestCheckinShift(unittest.TestCase):
	def test_the_shift_locked_at_check_in_is_found_by_its_work_date(self):
		from datetime import date, datetime

		from custom_hr.hrm.doctype.overtime_request.overtime_request import checkin_shift

		ins = [
			frappe._dict(shift="Malam", shift_work_date=date(2026, 10, 29), time=datetime(2026, 10, 29, 22, 0)),  # an outlet IN of the day before
			frappe._dict(shift="Pagi", shift_work_date=date(2026, 10, 30), time=datetime(2026, 10, 30, 7, 0)),
			frappe._dict(shift="Dept", shift_work_date=None, time=datetime(2026, 10, 31, 8, 0)),  # department IN: only its time
		]
		with patch("frappe.get_all", return_value=ins):
			self.assertEqual(checkin_shift("EMP-1", "2026-10-30"), "Pagi")
			self.assertEqual(checkin_shift("EMP-1", "2026-10-31"), "Dept")
			self.assertIsNone(checkin_shift("EMP-1", "2026-11-01"))

	def test_an_in_fills_only_that_days_overtime_rows_without_a_shift(self):
		from datetime import date, datetime

		from custom_hr.hrm.doctype.overtime_request.overtime_request import stamp_checkin_shift

		rows = [frappe._dict(name="ROW-1", parent="OT-SAME-DAY"), frappe._dict(name="ROW-2", parent="OT-OTHER-DAY")]
		def get_all(doctype, **kwargs):
			return rows if doctype == "Overtime Request Employee" else ["OT-SAME-DAY"]
		checkin = frappe._dict(log_type="IN", shift="Pagi", employee="EMP-1", shift_work_date=date(2026, 10, 30), time=datetime(2026, 10, 30, 7, 0))
		with patch("frappe.get_all", side_effect=get_all) as listing, patch("frappe.db.set_value") as write:
			stamp_checkin_shift(checkin)
			stamp_checkin_shift(frappe._dict(checkin, log_type="OUT"))
			stamp_checkin_shift(frappe._dict(checkin, shift=None))
		self.assertEqual([call.args for call in write.call_args_list], [
			("Overtime Request Employee", "ROW-1", "shift", "Pagi"),
			("Overtime List", {"overtime_request": "OT-SAME-DAY", "employee": "EMP-1"}, "shift", "Pagi"),  # an approved row follows
		])
		self.assertEqual(listing.call_args_list[0].kwargs["filters"]["shift"], ["is", "not set"])  # a shift already set is kept
