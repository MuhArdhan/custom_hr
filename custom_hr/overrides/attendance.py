import frappe
from hrms.hr.doctype.attendance.attendance import Attendance


class CustomAttendance(Attendance):
	"""Izin per jam: the employee still works that day, so its leave must not turn the attendance into On Leave."""

	def check_leave_record(self):
		status, leave_type, leave_application = self.status, self.leave_type, self.leave_application
		super().check_leave_record()
		if self.leave_application and frappe.db.get_value("Leave Application", self.leave_application, "izin_per_jam"):
			self.status, self.leave_type, self.leave_application = status, leave_type, leave_application
