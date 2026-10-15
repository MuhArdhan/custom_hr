# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Employee Checkin overrides.

Adds, without touching the hrms app:
- self-service restrictions (one IN per day, no backdating, check-out window)
- face verification requirement
- native realtime attendance marking after check-out (outlet pairs wait for T08)
- immutable outlet IN snapshots and OUT pairing, with activation still gated
- coordinates are stored even when geolocation tracking is off
"""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime

from hrms.hr.doctype.employee_checkin.employee_checkin import (
	EmployeeCheckin as BaseEmployeeCheckin,
)

from custom_hr.services.outlet_checkin import (
	prepare_or_protect_checkin,
	prevent_locked_checkin_deletion,
)
from custom_hr.services.outlet_shift import normalize_checkin_datetime

# users with any of these roles bypass the self-service checkin restrictions
SELF_SERVICE_BYPASS_ROLES = {"HR Manager", "HR User", "System Manager"}
# allowed clock drift between server time and the submitted log time (in seconds)
SELF_CHECKIN_TIME_TOLERANCE_SECONDS = 900


class CustomEmployeeCheckin(BaseEmployeeCheckin):
	def before_validate(self):
		if self.is_new() or not self.get("name"):
			try:
				self.time = normalize_checkin_datetime(self.time)
			except (ValueError, TypeError, OverflowError, KeyError):
				frappe.throw(_("Waktu absen atau timezone site tidak valid."))
			super().before_validate()
			prepare_or_protect_checkin(self)
		else:
			# Check immutable fields against DB before even normalizing a
			# potentially forged timestamp on an existing locked document.
			prepare_or_protect_checkin(self)
			super().before_validate()

	def validate(self):
		super().validate()
		self.validate_self_service_checkin()

	@frappe.whitelist()
	def fetch_shift(self):
		if not prepare_or_protect_checkin(self):
			return super().fetch_shift()

	def on_trash(self):
		prevent_locked_checkin_deletion(self)

	def set_geolocation(self):
		# upstream gates this behind HR Settings; store the payload whenever
		# coordinates are present so the check-in history can show a location
		if not (self.latitude and self.longitude):
			return

		self.geolocation = frappe.json.dumps(
			{
				"type": "FeatureCollection",
				"features": [
					{
						"type": "Feature",
						"properties": {},
						# geojson needs coordinates in reverse order: long, lat
						"geometry": {"type": "Point", "coordinates": [self.longitude, self.latitude]},
					}
				],
			}
		)

	def validate_self_service_checkin(self):
		"""Restrict employee self-service check-ins:
		- no backdated/future logs (time must be close to server time)
		- face verification required when configured
		- check-out only allowed when there is an open check-in within the allowed window
		"""
		if not self.is_new() or self.flags.get("ignore_checkin_restrictions"):
			return
		if self.get("attendance_source") == "Outlet":
			# Enforced under the employee lock in before_validate/fetch_shift,
			# including when a caller sets flags.ignore_validate.
			return

		if frappe.session.user == "Administrator" or set(frappe.get_roles()) & SELF_SERVICE_BYPASS_ROLES:
			return

		self.validate_self_service_time()
		self.validate_daily_checkin_limit()
		self.validate_face_verification()
		self.validate_checkout_window()

	def validate_daily_checkin_limit(self):
		"""Allow only one check-in per day (and one check-out via the open check-in rule)."""
		if self.log_type != "IN":
			return

		day_start = get_datetime(self.time).replace(hour=0, minute=0, second=0, microsecond=0)
		day_end = day_start + timedelta(days=1)
		if frappe.db.exists(
			"Employee Checkin",
			{
				"employee": self.employee,
				"log_type": "IN",
				"time": ["between", [day_start, day_end]],
				"name": ("!=", self.name),
			},
		):
			frappe.throw(
				title=_("Already Checked In"),
				msg=_("You have already checked in today. Please check out instead."),
			)

	def validate_self_service_time(self):
		server_time = now_datetime()
		if (
			self.get("attendance_source") == "Outlet" and self.log_type == "OUT"
			and self.get("checkout_deadline")
			and server_time.replace(microsecond=0) > get_datetime(self.checkout_deadline)
		):
			frappe.throw(_("Batas check-out sesi sudah lewat menurut waktu server. OUT kemarin tidak dapat dicatat dengan mengubah waktu perangkat; hubungi HR untuk koreksi Attendance."))
		drift = abs((get_datetime(self.time) - server_time).total_seconds())
		if drift > SELF_CHECKIN_TIME_TOLERANCE_SECONDS:
			frappe.throw(
				title=_("Invalid Check-in Time"),
				msg=_(
					"You cannot check in or out for a past or future time. "
					"Please raise an Attendance Request to regularize your attendance."
				),
			)

	def validate_face_verification(self):
		if not frappe.db.get_single_value("HR Settings", "require_face_checkin"):
			return

		if not self.face_verified:
			frappe.throw(
				title=_("Face Verification Required"),
				msg=_("Please verify your face in the mobile app to check in or out."),
			)

	def validate_checkout_window(self):
		if self.log_type != "OUT":
			return

		last_log = frappe.get_all(
			"Employee Checkin",
			filters={"employee": self.employee, "name": ("!=", self.name)},
			fields=["name", "log_type", "time", "shift_actual_end"],
			order_by="time desc",
			limit=1,
		)
		if not last_log or last_log[0].log_type != "IN":
			frappe.throw(_("No open check-in found. Please check in before checking out."))

		cutoff = get_checkout_cutoff(last_log[0])
		if get_datetime(self.time) > cutoff:
			frappe.throw(
				title=_("Check-out Window Expired"),
				msg=_(
					"Checking out for a previous day is not allowed. "
					"Please raise an Attendance Request to regularize your attendance."
				),
			)

	def after_insert(self):
		self.queue_realtime_attendance()

	def queue_realtime_attendance(self):
		"""Mark attendance as soon as a check-out completes the day's pair.

		Standard HRMS only finalises attendance after the shift ends via the
		hourly job, so a same-day check-in/out stays invisible to the employee
		calendar and HR until then.
		"""
		if self.log_type != "OUT" or not self.shift or cint(self.skip_auto_attendance):
			return
		if self.get("attendance_source") == "Outlet":
			# T06 records the pair only. T08 will enqueue the pair-scoped
			# processor; never advance a native shift-wide sync from this OUT.
			return
		frappe.enqueue(
			"custom_hr.overrides.employee_checkin.process_shift_attendance_now",
			queue="short",
			enqueue_after_commit=True,
			shift=self.shift,
			employee=self.employee,
		)


def process_shift_attendance_now(shift: str, employee: str) -> None:
	"""Process auto attendance for one employee's shift without waiting for shift end.

	Called right after a check-out; only runs when the check-in of the pair is
	still unmarked, and pulls `last_sync_of_checkin` forward so the standard
	shift-type processor picks the logs up.
	"""
	pending_in = frappe.db.exists(
		"Employee Checkin",
		{"employee": employee, "shift": shift, "log_type": "IN", "attendance": ("is", "not set")},
	)
	if not pending_in:
		return

	# jobs run as the enqueuing user (the employee); attendance marking needs HR rights
	frappe.set_user("Administrator")

	shift_doc = frappe.get_doc("Shift Type", shift)
	if not cint(shift_doc.enable_auto_attendance):
		return

	last_log = frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee, "shift": shift, "attendance": ("is", "not set")},
		fields=["shift_actual_end"],
		order_by="shift_actual_end desc",
		limit=1,
	)
	if last_log and last_log[0].shift_actual_end:
		last_sync = get_datetime(last_log[0].shift_actual_end) + timedelta(minutes=1)
		frappe.db.set_value("Shift Type", shift, "last_sync_of_checkin", last_sync)
		shift_doc.last_sync_of_checkin = last_sync

	shift_doc.process_auto_attendance()


def get_checkout_cutoff(open_checkin) -> "datetime":
	"""Check-out is allowed until the end of the day the shift (or check-in) belongs to."""
	if open_checkin.get("attendance_source") == "Outlet" and open_checkin.get("checkout_deadline"):
		return get_datetime(open_checkin.get("checkout_deadline"))
	reference_time = open_checkin.get("shift_actual_end") or open_checkin.get("time")
	return get_datetime(reference_time).replace(hour=23, minute=59, second=59, microsecond=0)
