"""Employee: "Create User Permission" restricts the user to their own Employee only.

ERPNext also locks the user to the Employee's Company; that lock is never created here, and one made
before goes on the next save (ERPNext only syncs when the user or the checkbox changes, this runs on every save).
"""

import frappe
from frappe.permissions import add_user_permission, remove_user_permission
from hrms.overrides.employee_master import EmployeeMaster


class CustomEmployee(EmployeeMaster):
	def update_user_permissions(self):
		if frappe.db.exists("User Permission", {"allow": "Company", "for_value": self.company, "user": self.user_id}):
			remove_user_permission("Company", self.company, self.user_id, ignore_permissions=True)
		restricted = frappe.db.exists("User Permission", {"allow": "Employee", "for_value": self.name, "user": self.user_id})
		if restricted and not self.create_user_permission:
			remove_user_permission("Employee", self.name, self.user_id, ignore_permissions=True)
		elif not restricted and self.create_user_permission:
			add_user_permission("Employee", self.name, self.user_id, ignore_permissions=True)
