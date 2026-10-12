# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Overtime Request: leader mengajukan lembur untuk sekelompok karyawan.

Approval berjenjang (Workflow "Pengajuan Lembur"):
Menunggu Leader -> [Menunggu SPV] -> Menunggu HRD -> Disetujui / Ditolak.

Saat disetujui, jenis lembur di-stamp ke Shift Assignment tiap karyawan pada
tanggal tersebut, sehingga rantai native HRMS mencatat lembur aktual:
Employee Checkin -> Attendance.overtime_type/actual_overtime_duration ->
Overtime Slip -> Additional Salary.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, time_diff_in_hours

from custom_hr.api.roster import HR_ROLES

FINAL_STATES = ("Disetujui", "Ditolak")
MAX_OVERTIME_HOURS = 4


class OvertimeRequest(Document):
	def validate(self):
		self.fetch_outlet_details()
		self.validate_editable()
		self.validate_times()
		self.validate_employees()
		self.validate_no_duplicate()
		self.guard_create_access()
		if self.is_new():
			# a new document must start at the first workflow state; the
			# self-submit skip happens right after insert, see after_insert
			self.status = "Menunggu Leader"
			self.flags.overtime_skip_target = self.initial_state()

	def after_insert(self):
		self.auto_advance()

	def auto_advance(self):
		"""When the requester is the level-1 approver (leader submitting on
		behalf of the crew) the leader level is skipped by applying the real
		workflow transition, so the skip shows up in the approval history."""
		target = self.flags.get("overtime_skip_target")
		if not target or target == "Menunggu Leader":
			return

		from frappe.model.workflow import apply_workflow, get_transitions

		transitions = get_transitions(self)
		action = next(
			(t.action for t in transitions if t.next_state == target), None
		)
		if action:
			apply_workflow(self, action)

	def on_update(self):
		if self.status == "Disetujui":
			self.stamp_assignments()

	def fetch_outlet_details(self):
		if not self.outlet:
			return
		outlet = frappe.get_cached_doc("Outlet", self.outlet)
		self.company = outlet.company
		if self.is_new():
			self.requested_by = self.requested_by or frappe.session.user
			self.approver_1 = outlet.approver_1
			self.approver_2 = outlet.approver_2

	def validate_editable(self):
		if self.is_new():
			return
		db_status = frappe.db.get_value("Overtime Request", self.name, "status")
		if db_status in FINAL_STATES and frappe.session.user != "Administrator":
			roles = frappe.get_roles()
			if "System Manager" not in roles:
				frappe.throw(_("Pengajuan {0} sudah {1} dan tidak dapat diubah").format(self.name, db_status))

	def validate_times(self):
		if not self.start_time or not self.end_time:
			frappe.throw(_("Jam mulai dan jam selesai wajib diisi"))
		hours = time_diff_in_hours(self.end_time, self.start_time)
		if hours <= 0:
			hours += 24
		if hours <= 0:
			frappe.throw(_("Jam selesai harus setelah jam mulai"))
		if hours > MAX_OVERTIME_HOURS:
			frappe.throw(
				_("Lembur maksimal {0} jam per pengajuan (PP 35/2021)").format(MAX_OVERTIME_HOURS)
			)
		self.planned_hours = flt(hours, 2)

	def validate_employees(self):
		if not self.employees:
			frappe.throw(_("Tambahkan minimal satu karyawan"))

		seen = set()
		for row in self.employees:
			if row.employee in seen:
				frappe.throw(_("Karyawan {0} muncul lebih dari sekali").format(row.employee_name or row.employee))
			seen.add(row.employee)

			employee = frappe.db.get_value(
				"Employee", row.employee, ["employee_name", "outlet"], as_dict=True
			)
			if not employee:
				frappe.throw(_("Karyawan {0} tidak ditemukan").format(row.employee))
			if employee.outlet != self.outlet:
				frappe.throw(
					_("{0} tidak berada di outlet {1}").format(
						employee.employee_name or row.employee, self.outlet
					)
				)

			assignment = frappe.get_all(
				"Shift Assignment",
				filters={
					"employee": row.employee,
					"docstatus": ["!=", 2],
					"status": "Active",
					"start_date": ["<=", self.date],
					"end_date": [">=", self.date],
				},
				fields=["shift_type"],
				ignore_permissions=True,
			)
			if not assignment:
				frappe.throw(
					_("Belum ada jadwal shift {0} pada {1}. Atur dulu di Roster Outlet.").format(
						employee.employee_name or row.employee, frappe.bold(self.date)
					)
				)

			row.employee_name = employee.employee_name
			row.shift = assignment[0].shift_type

	def validate_no_duplicate(self):
		employees = [row.employee for row in self.employees]
		other_requests = frappe.get_all(
			"Overtime Request",
			filters={
				"date": self.date,
				"status": ["!=", "Ditolak"],
				"name": ["!=", self.name or ""],
			},
			pluck="name",
			ignore_permissions=True,
		)
		if not other_requests:
			return
		duplicates = frappe.get_all(
			"Overtime Request Employee",
			filters={"parent": ["in", other_requests], "employee": ["in", employees]},
			fields=["employee"],
			ignore_permissions=True,
		)
		if duplicates:
			names = ", ".join(
				frappe.db.get_value("Employee", row.employee, "employee_name") or row.employee
				for row in duplicates
			)
			frappe.throw(
				_("Sudah ada pengajuan lembur aktif untuk {0} pada tanggal ini").format(names)
			)

	def guard_create_access(self):
		if not self.is_new():
			return
		user = frappe.session.user
		if set(HR_ROLES) & set(frappe.get_roles(user)):
			return
		if user and user in (self.approver_1, self.approver_2):
			return
		frappe.throw(
			_("Anda tidak punya akses membuat pengajuan untuk outlet ini"), frappe.PermissionError
		)

	def initial_state(self):
		user = frappe.session.user
		if self.approver_1 and self.approver_1 != user:
			return "Menunggu Leader"
		if self.approver_2 and self.approver_2 not in (user, self.approver_1):
			return "Menunggu SPV"
		return "Menunggu HRD"

	def stamp_assignments(self):
		stamped = 0
		for row in self.employees:
			assignments = frappe.get_all(
				"Shift Assignment",
				filters={
					"employee": row.employee,
					"docstatus": ["!=", 2],
					"status": "Active",
					"start_date": ["<=", self.date],
					"end_date": [">=", self.date],
				},
				pluck="name",
				ignore_permissions=True,
			)
			for name in assignments:
				if frappe.db.get_value("Shift Assignment", name, "overtime_type") != self.overtime_type:
					frappe.db.set_value(
						"Shift Assignment", name, "overtime_type", self.overtime_type
					)
					stamped += 1

		if stamped:
			self.add_comment(
				"Info",
				_("Jenis lembur {0} diterapkan ke {1} jadwal shift").format(
					self.overtime_type, stamped
				),
			)
