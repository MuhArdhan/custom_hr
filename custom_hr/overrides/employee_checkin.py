# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Employee Checkin overrides.

Adds, without touching the hrms app:
- self-service restrictions (one IN per day, no backdating, check-out window)
- face verification requirement
- pair-scoped outlet attendance and native realtime marking after check-out
- immutable outlet IN snapshots and OUT pairing, with activation still gated
- coordinates are stored even when geolocation tracking is off
"""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime

from hrms.hr.doctype.employee_checkin.employee_checkin import (
	EmployeeCheckin as BaseEmployeeCheckin,
)

from custom_hr.services.outlet_checkin import (
	_employee_record,
	prepare_or_protect_checkin,
)
from custom_hr.services.outlet_shift import normalize_checkin_datetime
from custom_hr.services.checkin_submission import apply_verified_face
from custom_hr.services.department_shift import apply_department_shift
from custom_hr.services.outlet_geofence import coordinates, validate_outlet_geofence

# users with any of these roles bypass the self-service checkin restrictions
SELF_SERVICE_BYPASS_ROLES = {"HR Manager", "HR User", "System Manager"}
# allowed clock drift between server time and the submitted log time (in seconds)
SELF_CHECKIN_TIME_TOLERANCE_SECONDS = 900


class CustomEmployeeCheckin(BaseEmployeeCheckin):
	def before_validate(self):
		if self.is_new() or not self.get("name"):
			if not (frappe.session.user == "Administrator" or set(frappe.get_roles()) & SELF_SERVICE_BYPASS_ROLES):
				# Device time/flags and face_verified in raw REST payloads are not proof.
				_employee_record(self.employee, for_update=True)
				self.time = now_datetime()
				apply_verified_face(self)
			try:
				self.time = normalize_checkin_datetime(self.time)
			except (ValueError, TypeError, OverflowError, KeyError):
				frappe.throw(_("Waktu absen atau timezone site tidak valid."))
			super().before_validate()
			uses_outlet = prepare_or_protect_checkin(self)
			if uses_outlet:
				# before_validate still runs with ignore_validate: no raw REST,
				# face/ordinary endpoint, or HR flag can skip outlet geofencing.
				self.validate_distance_from_shift_location()
				self.set_geolocation()
			if not uses_outlet and not (frappe.session.user == "Administrator" or set(frappe.get_roles()) & SELF_SERVICE_BYPASS_ROLES):
				self.validate_self_service_time()
				self.validate_daily_checkin_limit()
				self.validate_face_verification()
				self.validate_checkout_window()
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
		if not prepare_or_protect_checkin(self) and not apply_department_shift(self):
			return super().fetch_shift()

	def validate_distance_from_shift_location(self):
		if not validate_outlet_geofence(self):
			return super().validate_distance_from_shift_location()

	def set_geolocation(self):
		# upstream gates this behind HR Settings; store the payload whenever
		# coordinates are present so the check-in history can show a location
		if self.get("attendance_source") == "Outlet":
			try:
				lat, lon = coordinates(self.latitude, self.longitude)
			except ValueError:
				return  # No fictitious (0, 0) map when optional GPS is absent.
			self.latitude = flt(lat, self.precision("latitude"))
			self.longitude = flt(lon, self.precision("longitude"))
		elif not (self.latitude and self.longitude):
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
		log = frappe.qb.DocType("Employee Checkin")
		condition = (
			(log.employee == self.employee) & (log.log_type == "IN")
			& (log.time >= day_start) & (log.time < day_end)
		)
		if self.name:
			condition &= log.name != self.name
		if frappe.qb.from_(log).select(log.name).where(condition).limit(1).for_update().run():
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

		log = frappe.qb.DocType("Employee Checkin")
		condition = log.employee == self.employee
		if self.name:
			condition &= log.name != self.name
		last_log = (
			frappe.qb.from_(log).select(log.name, log.log_type, log.time, log.shift_actual_end)
			.where(condition).orderby(log.time, log.name, order=frappe.qb.desc)
			.limit(1).for_update().run(as_dict=True)
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
		from custom_hr.hrm.doctype.overtime_request.overtime_request import stamp_checkin_shift

		stamp_checkin_shift(self)

	def queue_realtime_attendance(self):
		"""Mark attendance as soon as a check-out completes the day's pair.

		Standard HRMS only finalises attendance after the shift ends via the
		hourly job, so a same-day check-in/out stays invisible to the employee
		calendar and HR until then.
		"""
		if self.log_type != "OUT" or not self.shift or cint(self.skip_auto_attendance):
			return
		if self.get("attendance_source") == "Outlet":
			frappe.enqueue(
				"custom_hr.services.outlet_attendance.process_outlet_attendance",
				queue="short", enqueue_after_commit=True,
				source_checkin=self.paired_checkin, source_checkout=self.name,
			)
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
	log = frappe.qb.DocType("Employee Checkin")
	native = log.attendance_source.isnull() | (log.attendance_source != "Outlet")
	pending_in = (
		frappe.qb.from_(log).select(log.name).where(
			(log.employee == employee) & (log.shift == shift) & (log.log_type == "IN")
			& (log.attendance.isnull() | (log.attendance == "")) & native
		).limit(1).run()
	)
	if not pending_in:
		return

	# jobs run as the enqueuing user (the employee); attendance marking needs HR rights
	frappe.set_user("Administrator")

	shift_doc = frappe.get_doc("Shift Type", shift)
	if not cint(shift_doc.enable_auto_attendance):
		return

	last_log = (
		frappe.qb.from_(log).select(log.shift_actual_end).where(
			(log.employee == employee) & (log.shift == shift)
			& (log.attendance.isnull() | (log.attendance == "")) & native
		).orderby(log.shift_actual_end, order=frappe.qb.desc).limit(1).run(as_dict=True)
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
