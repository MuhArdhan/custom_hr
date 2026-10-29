# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Overtime Request: leader mengajukan lembur untuk sekelompok karyawan.

Admin memilih Company; outlet (tersembunyi) mengikuti Company karena nama Outlet
sama dengan Company-nya. Kru outlet: approval berjenjang Leader/SPV lalu HRD.
Company tanpa outlet (pabrik/gudang): approver kosong sehingga pengajuan
langsung masuk antrean HRD.

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
from frappe.utils import add_days, flt, getdate, time_diff_in_hours

from custom_hr.api.roster import HR_ROLES
from custom_hr.services.overtime_approval import DECISION_TOKEN, SELF_REQUEST_TOKEN, employee_state, protect_employee_decisions

FINAL_STATES = ("Disetujui", "Ditolak")


def checkin_shift(employee, day):
	"""The shift the employee locked at check-in on that work date, the one actually worked.

	Outlet check-ins carry their work date; Department check-ins only their time.
	"""
	day = getdate(day)
	ins = frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee, "log_type": "IN", "shift": ["is", "set"], "time": ["between", [f"{add_days(day, -1)} 00:00:00", f"{add_days(day, 1)} 23:59:59"]]},
		fields=["shift", "shift_work_date", "time"], order_by="time asc",
	)
	return next((row.shift for row in ins if getdate(row.shift_work_date or row.time) == day), None)


def stamp_checkin_shift(checkin):
	"""After an IN, fill the shift of that day's overtime rows still without one (requests can be made days ahead)."""
	if checkin.log_type != "IN" or not checkin.shift:
		return
	day = getdate(checkin.get("shift_work_date") or checkin.time)
	rows = frappe.get_all(
		"Overtime Request Employee",
		filters={"employee": checkin.employee, "parenttype": "Overtime Request", "shift": ["is", "not set"]},
		fields=["name", "parent"],
	)
	same_day = set(frappe.get_all("Overtime Request", filters={"name": ["in", [row.parent for row in rows]], "date": day}, pluck="name")) if rows else set()
	for row in rows:
		if row.parent in same_day:
			# a plain column write: a decided request must keep its approval history untouched
			frappe.db.set_value("Overtime Request Employee", row.name, "shift", checkin.shift, update_modified=False)


class OvertimeRequest(Document):
	def validate(self):
		protect_employee_decisions(self)
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
			self.flags.employee_initialization_token = DECISION_TOKEN
			try:
				apply_workflow(self, action)
			finally:
				self.flags.pop("employee_initialization_token", None)
		else:
			# no workflow step skips an empty approver level (HR may only decide at Menunggu HRD),
			# and the target comes from initial_state, never from the request
			self.db_set("status", target)
			self.add_comment("Workflow", _("Tanpa approver: langsung {0}").format(target))

	def validate_workflow(self):
		# The employee transition was checked against the same Workflow before
		# save. Parent status is only an aggregate and can differ from that row.
		if self.flags.get("employee_decision_token") is not DECISION_TOKEN:
			return super().validate_workflow()

	def on_update(self):
		if self.status == "Disetujui" or self.flags.get("employee_decision_token") is DECISION_TOKEN:
			self.stamp_assignments()

	def fetch_outlet_details(self):
		"""Outlets are named after their Company (as on Employee): the hidden outlet follows the chosen company."""
		if not self.company and self.employees:
			self.company = frappe.db.get_value("Employee", self.employees[0].employee, "company")
		self.outlet = self.company if self.company and frappe.db.exists("Outlet", self.company) else None
		if not self.outlet:
			return  # a company without an outlet (factory, warehouse): no approvers, straight to HRD
		outlet = frappe.get_cached_doc("Outlet", self.outlet)
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
		# the cap is the Overtime Type's own; 0 or empty means no cap, as in the native Overtime Slip
		limit = flt(frappe.db.get_value("Overtime Type", self.overtime_type, "maximum_overtime_hours_allowed")) if self.overtime_type else 0
		if limit and hours > limit:
			frappe.throw(
				_("Jenis lembur {0} maksimal {1} jam per pengajuan").format(self.overtime_type, f"{flt(limit, 2):g}")
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
				"Employee", row.employee, ["employee_name", "outlet", "company"], as_dict=True
			)
			if not employee:
				frappe.throw(_("Karyawan {0} tidak ditemukan").format(row.employee))
			if employee.company != self.company:  # one company, so one outlet and one set of approvers
				frappe.throw(
					_("{0} bukan karyawan {1}").format(
						employee.employee_name or row.employee, self.company
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
			# a shift is optional: requests are reported now, payroll (which needs the shift) comes later
			row.employee_name = employee.employee_name
			# a shift picked in the form is kept; an empty one comes from the check-in, then the assignment
			row.shift = row.shift or checkin_shift(row.employee, self.date) or (assignment[0].shift_type if assignment else None)

	def validate_no_duplicate(self):
		employees = [row.employee for row in self.employees if employee_state(self, row) != "Ditolak"]
		if not employees:
			return
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
			fields=["employee", "approval_state"],
			ignore_permissions=True,
		)
		duplicates = [row for row in duplicates if row.get("approval_state") != "Ditolak"]
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
		if self.is_self_request():
			return
		frappe.throw(
			_("Anda tidak punya akses membuat pengajuan untuk outlet ini"), frappe.PermissionError
		)

	def is_self_request(self):
		"""Created from the HRMS app by an employee, for that employee alone."""
		if self.flags.get("overtime_self_request") is not SELF_REQUEST_TOKEN:
			return False
		own = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
		return bool(own) and [row.employee for row in self.employees] == [own]

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
			if employee_state(self, row) != "Disetujui":
				continue
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
