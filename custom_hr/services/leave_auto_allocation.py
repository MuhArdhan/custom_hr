"""Leave Type auto allocation: a fresh submitted Leave Allocation per active (outlet / non-outlet) employee every period.

Each allocation covers exactly one period, so unused leave expires with it (e.g. Izin Sakit 2x per month).
"""

from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, getdate

PERIOD_MONTHS = {"Monthly": 1, "Quarterly": 3, "Yearly": 12}
# Outlet employees are the ones with Employee.outlet set.
APPLIES_TO = {"All Employees": {}, "Outlet": {"outlet": ["is", "set"]}, "Non-Outlet": {"outlet": ["is", "not set"]}}


def period_for(day, every: str, start_day: int) -> tuple[date, date]:
	"""The period containing `day`; periods start on `start_day` and are aligned to January."""
	day, months = getdate(day), PERIOD_MONTHS[every]
	index = day.year * 12 + day.month - 1 - (day.day < start_day)  # before the start day = previous month's period
	index -= index % months
	start = date(index // 12, index % 12 + 1, start_day)
	return start, add_months(start, months) - timedelta(days=1)


def validate_leave_type(doc, method=None):
	"""Leave Type validate: auto allocation needs a positive amount, a period and a start day every month has."""
	if not doc.get("auto_allocate"):
		return
	if doc.is_lwp:
		frappe.throw(_("Leave Without Pay cannot be allocated automatically."))
	if flt(doc.auto_allocate_leaves) <= 0:
		frappe.throw(_("Leaves per Period must be more than 0."))
	if doc.auto_allocate_every not in PERIOD_MONTHS:
		frappe.throw(_("Choose an Allocation Period."))
	if (doc.get("auto_allocate_for") or "All Employees") not in APPLIES_TO:
		frappe.throw(_("Choose who the allocation Applies To."))
	if not 1 <= cint(doc.auto_allocate_start_day) <= 28:
		frappe.throw(_("Period Starts On Day must be between 1 and 28."))


def on_leave_type_update(doc, method=None):
	"""Give everyone the current period right away instead of waiting for the daily job."""
	if doc.get("auto_allocate"):
		frappe.enqueue(allocate, queue="long", leave_type=doc.name, enqueue_after_commit=True)


def allocate(today=None, leave_type=None):
	"""Daily job: create the current period's allocation for every active employee who has none yet."""
	filters = {"auto_allocate": 1, **({"name": leave_type} if leave_type else {})}
	created = []
	for row in frappe.get_all("Leave Type", filters=filters, fields=["name", "auto_allocate_every", "auto_allocate_leaves", "auto_allocate_start_day", "auto_allocate_for"]):
		from_date, to_date = period_for(today or getdate(), row.auto_allocate_every, cint(row.auto_allocate_start_day) or 1)
		allocated = set(frappe.get_all(
			"Leave Allocation",
			filters={"leave_type": row.name, "docstatus": 1, "from_date": ["<=", to_date], "to_date": [">=", from_date]},
			pluck="employee",
		))
		employees = frappe.get_all(
			"Employee",
			filters={"status": "Active", "date_of_joining": ["<=", to_date], **APPLIES_TO.get(row.auto_allocate_for or "All Employees", {})},
			or_filters=[["relieving_date", "is", "not set"], ["relieving_date", ">=", from_date]],
			pluck="name",
		)
		for employee in employees:
			if employee in allocated:
				continue
			frappe.db.savepoint("leave_auto_allocation")
			try:
				frappe.get_doc({
					"doctype": "Leave Allocation", "employee": employee, "leave_type": row.name,
					"from_date": from_date, "to_date": to_date, "new_leaves_allocated": flt(row.auto_allocate_leaves),
				}).insert(ignore_permissions=True).submit()
				created.append((employee, row.name))
			except Exception:
				# One employee's bad data must not stop everyone else's allocation.
				frappe.db.rollback(save_point="leave_auto_allocation")
				frappe.log_error(title=f"Leave auto allocation failed: {employee} / {row.name}")
	return created
