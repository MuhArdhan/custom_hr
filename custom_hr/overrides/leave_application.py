from hrms.hr.doctype.leave_application.leave_application import LeaveApplication


class CustomLeaveApplication(LeaveApplication):
	"""Izin per jam: the employee still works that day, so a check-in may exist and attendance stays as it is."""

	def validate_attendance(self):
		if not self.get("izin_per_jam"):
			super().validate_attendance()

	def update_attendance(self):
		if not self.get("izin_per_jam"):
			super().update_attendance()

	def cancel_attendance(self):
		if not self.get("izin_per_jam"):
			super().cancel_attendance()
