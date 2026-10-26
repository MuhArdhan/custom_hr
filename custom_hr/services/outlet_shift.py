# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

"""Read-only shift selection. Not an API, check-in writer or permission check.

Naive timestamps use the site timezone; aware timestamps are converted to it.
Preview may inspect a disabled outlet mode but never enables it. Callers must
re-resolve without preview before accepting an IN (T05/T07).
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from math import isfinite
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, get_system_timezone, get_time, now_datetime

SNAPSHOT_VERSION = 1
SHIFT_FIELDS = (
	"name",
	"modified",
	"start_time",
	"end_time",
	"determine_check_in_and_check_out",
	"working_hours_calculation_based_on",
	"enable_auto_attendance",
	"enable_late_entry_marking",
	"late_entry_grace_period",
	"enable_early_exit_marking",
	"early_exit_grace_period",
	"working_hours_threshold_for_half_day",
	"working_hours_threshold_for_absent",
	"mark_auto_attendance_on_holidays",
	"allow_overtime",
	"overtime_type",
)
FLAG_FIELDS = (
	"enable_auto_attendance",
	"enable_late_entry_marking",
	"enable_early_exit_marking",
	"mark_auto_attendance_on_holidays",
	"allow_overtime",
)
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class ShiftConfigurationError(ValueError):
	"""Invalid or ambiguous schedule: never silently fall back to a native shift."""


@dataclass(frozen=True)
class ShiftWindow:
	shift: str
	work_date: date
	shift_start: datetime
	shift_end: datetime
	checkin_start: datetime
	checkin_end: datetime
	end_inclusive: bool
	policy: dict

	def contains(self, timestamp: datetime) -> bool:
		return self.checkin_start <= timestamp and (
			timestamp <= self.checkin_end if self.end_inclusive else timestamp < self.checkin_end
		)

	def as_dict(self) -> dict:
		return {
			"shift": self.shift,
			"shift_work_date": self.work_date.isoformat(),
			"shift_start": str(self.shift_start),
			"shift_end": str(self.shift_end),
			"checkin_start": str(self.checkin_start),
			"checkin_end": str(self.checkin_end),
			"checkin_end_inclusive": self.end_inclusive,
		}


def _number(value, label: str, *, integer: bool = False) -> Decimal:
	try:
		number = Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		raise ShiftConfigurationError(_("{0} harus berupa angka tidak negatif.").format(label)) from None
	if not number.is_finite() or number < 0:
		raise ShiftConfigurationError(_("{0} harus berupa angka tidak negatif.").format(label))
	if integer and number != number.to_integral_value():
		raise ShiftConfigurationError(_("{0} harus berupa bilangan bulat.").format(label))
	return number


def _clock(value, shift_name: str) -> time:
	if value is None or value == "" or not isinstance(value, (str, time, timedelta)):
		raise ShiftConfigurationError(_("Jam shift {0} tidak valid.").format(shift_name))
	if isinstance(value, timedelta) and not timedelta() <= value < timedelta(days=1):
		raise ShiftConfigurationError(_("Jam shift {0} harus berada dalam satu hari.").format(shift_name))
	try:
		if isinstance(value, str):
			parts = value.split(":")
			if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
				raise ValueError("invalid clock format")
			# get_time() can wrap values like 25:00 into the next day. Shift
			# definitions must be actual wall clocks, not normalized durations.
			clock = time(*(int(part) for part in parts))
		else:
			clock = get_time(value)
	except (TypeError, ValueError, OverflowError):
		raise ShiftConfigurationError(_("Jam shift {0} tidak valid.").format(shift_name)) from None
	if clock.tzinfo is not None or clock.microsecond:
		raise ShiftConfigurationError(_("Jam shift {0} harus menggunakan jam lokal dengan ketelitian detik.").format(shift_name))
	return clock


def _policy(shift: dict) -> dict:
	policy = {"shift_type_modified": str(shift.get("modified") or "")}
	for field in FLAG_FIELDS:
		value = _number(shift.get(field, 0), field, integer=True)
		if value not in (0, 1):
			raise ShiftConfigurationError(_("Nilai pengaturan {0} harus 0 atau 1.").format(field))
		policy[field] = int(value)
	for field in ("late_entry_grace_period", "early_exit_grace_period"):
		policy[field] = int(_number(shift.get(field), _("Toleransi waktu"), integer=True))
	for field in ("working_hours_threshold_for_half_day", "working_hours_threshold_for_absent"):
		policy[field] = float(_number(shift.get(field), _("Threshold jam kerja")))
		if not isfinite(policy[field]):
			raise ShiftConfigurationError(_("Threshold jam kerja berada di luar rentang angka yang didukung."))
	log_method = shift.get("determine_check_in_and_check_out")
	if log_method not in (
		"Strictly based on Log Type in Employee Checkin",
		"Alternating entries as IN and OUT during the same shift",
	):
		raise ShiftConfigurationError(_("Atur metode penentuan IN/OUT pada Shift Type {0}.").format(shift["name"]))
	hours_method = shift.get("working_hours_calculation_based_on")
	if hours_method not in ("First Check-in and Last Check-out", "Every Valid Check-in and Check-out"):
		raise ShiftConfigurationError(_("Atur metode perhitungan jam kerja pada Shift Type {0}.").format(shift["name"]))
	policy.update(
		determine_check_in_and_check_out=log_method,
		working_hours_calculation_based_on=hours_method,
		overtime_type=shift.get("overtime_type"),
	)
	if policy["allow_overtime"] and not policy["overtime_type"]:
		raise ShiftConfigurationError(_("Jenis lembur Shift Type {0} belum diisi.").format(shift["name"]))
	return policy


def row_weekdays(row) -> frozenset[int]:
	"""Weekdays (0 = Monday) a shift row applies on; no day checked means every day."""
	checked = frozenset(index for index, field in enumerate(WEEKDAYS) if row.get(field))
	return checked or frozenset(range(7))


def applies_on(row, day: date) -> bool:
	return day.weekday() in row_weekdays(row)


def active_shift_names(rows, day: date) -> list[str]:
	"""Shift Types in force on `day`: enabled rows whose weekdays include it."""
	return [row.shift_type for row in rows if row.get("enabled") and applies_on(row, day)]


def build_shift_windows(shifts: list[dict], work_date: date, transition_minutes: int) -> list[ShiftWindow]:
	"""Build one work-date's windows from active shifts, independent of DB writes.

	The first window opens at midnight; subsequent windows open before their
	start by the outlet transition. No shift can accept IN after its own end.
	This also leaves a closed interval if two shifts have a real operational gap.
	"""
	transition = _number(transition_minutes, _("Jeda Peralihan IN"), integer=True)
	if transition >= 1440:
		raise ShiftConfigurationError(_("Jeda Peralihan IN harus kurang dari satu hari."))
	if not isinstance(work_date, date) or isinstance(work_date, datetime):
		raise ShiftConfigurationError(_("Tanggal kerja harus berupa tanggal lokal."))
	if not shifts:
		raise ShiftConfigurationError(_("Outlet belum memiliki shift aktif."))
	definitions = []
	names = set()
	for shift in shifts:
		name = shift.get("name")
		if not name or name in names:
			raise ShiftConfigurationError(_("Daftar shift aktif kosong atau memiliki Shift Type duplikat."))
		start, end = _clock(shift.get("start_time"), name), _clock(shift.get("end_time"), name)
		if start == end:
			raise ShiftConfigurationError(_("Jam mulai shift aktif bertabrakan atau sama dengan jam selesai."))
		names.add(name)
		definitions.append((start, end, name, _policy(shift)))
	definitions.sort(key=lambda row: (row[0], row[2]))
	midnight = datetime.combine(work_date, time.min)
	delta = timedelta(minutes=int(transition))
	windows = []
	for start, end, name, policy in definitions:
		shift_start = datetime.combine(work_date, start)
		shift_end = datetime.combine(work_date, end)
		if end < start:
			shift_end += timedelta(days=1)
		# Shifts sharing a start time share the same opening and the same next-start transition
		checkin_start = midnight if start == definitions[0][0] else shift_start - delta
		later_starts = [other[0] for other in definitions if other[0] > start]
		transition_at = datetime.combine(work_date, min(later_starts)) - delta if later_starts else None
		# A cutoff after shift end never reopens an already-finished shift.
		checkin_end = min(shift_end, transition_at) if transition_at is not None else shift_end
		inclusive = transition_at is None or shift_end < transition_at
		if checkin_start < midnight or checkin_end < checkin_start or (checkin_end == checkin_start and not inclusive):
			raise ShiftConfigurationError(_("Jeda peralihan menghasilkan jendela IN tidak valid pada shift {0}.").format(name))
		windows.append(ShiftWindow(name, work_date, shift_start, shift_end, checkin_start, checkin_end, inclusive, policy))
	return windows


def _local_datetime(value, timezone: str) -> datetime:
	if value is None:
		value = now_datetime()
	if isinstance(value, str) and not value.strip():
		raise ValueError("empty timestamp")
	if not isinstance(value, (str, datetime)):
		raise ValueError("timestamp must be a datetime or datetime string")
	parsed = get_datetime(value)
	if not isinstance(parsed, datetime):
		raise ValueError("invalid timestamp")
	zone = ZoneInfo(timezone)
	if parsed.tzinfo is not None:
		parsed = parsed.astimezone(zone).replace(tzinfo=None)
	# Employee Checkin stores whole seconds in its before_validate lifecycle.
	return parsed.replace(microsecond=0)


def normalize_checkin_datetime(timestamp=None) -> datetime:
	"""Normalize an IN timestamp to the same site-local seconds as the resolver."""
	return _local_datetime(timestamp, get_system_timezone())


def _read_context(employee: str, timestamp, *, for_update: bool = False) -> tuple[dict, object | None]:
	timezone = get_system_timezone()
	context = {
		"employee": employee,
		"outlet": None,
		"company": None,
		"timezone": timezone,
		"evaluated_at": None,
		"mode": "Unavailable",
		"mode_applies": False,
		"effective_from": None,
		"mode_reason": None,
		"message": "",
	}
	try:
		local_time = _local_datetime(timestamp, timezone)
	except (ValueError, TypeError, OverflowError, KeyError):
		context.update(mode_reason="invalid_timestamp", message=_("Waktu absen atau timezone site tidak valid."))
		return context, None
	context["evaluated_at"] = str(local_time)
	if not isinstance(employee, str) or not employee.strip():
		context.update(mode_reason="employee_not_found", message=_("Karyawan tidak ditemukan."))
		return context, None
	lock_options = {"for_update": True} if for_update else {}
	record = frappe.db.get_value("Employee", employee, ["name", "status", "outlet", "company"], as_dict=True, **lock_options)
	if not record:
		context.update(mode_reason="employee_not_found", message=_("Karyawan tidak ditemukan."))
		return context, None
	context.update(company=record.company, outlet=record.outlet)
	if record.status != "Active":
		context.update(mode_reason="employee_inactive", message=_("Karyawan tidak aktif."))
		return context, None
	if not record.company:
		context.update(mode_reason="invalid_configuration", message=_("Company karyawan belum ditentukan."))
		return context, None
	if not record.outlet:
		context.update(mode="Native", mode_reason="no_outlet", message=_("Karyawan tidak terhubung ke outlet; gunakan alur HRMS native."))
		return context, None
	try:
		outlet = frappe.get_doc("Outlet", record.outlet, **lock_options)
	except frappe.DoesNotExistError:
		context.update(mode_reason="outlet_not_found", message=_("Outlet karyawan tidak ditemukan."))
		return context, None
	if not outlet.is_active:
		context.update(mode_reason="outlet_inactive", message=_("Outlet karyawan tidak aktif."))
		return context, None
	# Outlet is the operational schedule/holiday/location source, not the
	# employing company. Its legacy Company mapping need not match Employee.
	if not outlet.get("enable_outlet_auto_shift"):
		context.update(mode="Native", mode_reason="mode_disabled", message=_("Mode shift otomatis outlet belum diaktifkan."))
		return context, outlet
	if not outlet.get("outlet_auto_shift_effective_from"):
		context.update(mode_reason="invalid_configuration", message=_("Waktu mulai mode shift otomatis belum ditentukan."))
		return context, outlet
	try:
		effective = _local_datetime(outlet.outlet_auto_shift_effective_from, timezone)
	except (ValueError, TypeError, OverflowError, KeyError):
		context.update(mode_reason="invalid_configuration", message=_("Waktu mulai mode shift otomatis tidak valid."))
		return context, outlet
	context["effective_from"] = str(effective)
	if local_time < effective:
		context.update(mode="Native", mode_reason="not_effective_yet", message=_("Mode shift otomatis belum berlaku pada waktu absen ini."))
		return context, outlet
	context.update(mode="Outlet", mode_applies=True, mode_reason="outlet_mode", message=_("Penentuan shift mengikuti outlet karyawan."))
	return context, outlet


def get_employee_attendance_mode(employee: str, timestamp=None, *, for_update: bool = False) -> dict:
	"""Internal mode lookup; does not choose a shift or authorize a user."""
	context, _outlet = _read_context(employee, timestamp, for_update=for_update)
	return context


def shift_windows(rows, shifts: list[dict], local_time: datetime, transition_minutes: int) -> list[ShiftWindow]:
	"""Windows that may accept an IN at `local_time`: today's shifts plus yesterday's overnight ones."""

	def shifts_on(day):
		names = set(active_shift_names(rows, day))
		return [shift for shift in shifts if shift.name in names]

	today = local_time.date()
	todays = shifts_on(today)
	windows = build_shift_windows(todays, today, transition_minutes) if todays else []
	yesterday = shifts_on(today - timedelta(days=1))
	previous = build_shift_windows(yesterday, today - timedelta(days=1), transition_minutes) if yesterday else []
	return [window for window in previous if window.checkin_end >= datetime.combine(today, time.min)] + windows


def resolve_outlet_shift(
	employee: str, timestamp=None, *, preview: bool = False, for_update: bool = False, chosen_shift: str | None = None
) -> dict:
	"""Return selection + JSON-ready snapshot, or a stable code and reason.

	Shifts sharing a start time are an employee choice: `choices` lists them and `chosen_shift` picks one.

	No writes, activation, historical backfill, Shift Assignment fallback, user
	permission bypass or HTTP exposure. Expected failures are returned, not thrown.
	"""
	context, outlet = _read_context(employee, timestamp, for_update=for_update)
	result = {
		**context,
		"preview": preview,
		"matched": False,
		"code": context["mode_reason"],
		"windows": [],
		"candidates": [],
		"choices": [],
		"selection": None,
		"checkin_values": None,
	}
	if context["mode"] == "Unavailable" or (not context["mode_applies"] and not preview) or outlet is None:
		return result
	try:
		active_names = [row.shift_type for row in (outlet.get("shifts") or []) if row.enabled]
		if not active_names or any(not name for name in active_names):
			raise ShiftConfigurationError(_("Outlet belum memiliki daftar shift aktif yang lengkap."))
		if len(active_names) != len(set(active_names)):
			raise ShiftConfigurationError(_("Shift Type aktif tercantum lebih dari sekali pada outlet."))
		if for_update:
			shift_table = frappe.qb.DocType("Shift Type")
			shifts = (
				frappe.qb.from_(shift_table).select(*(shift_table[field] for field in SHIFT_FIELDS))
				.where(shift_table.name.isin(sorted(active_names))).orderby(shift_table.name)
				.for_update().run(as_dict=True)
			)
		else:
			shifts = frappe.get_all("Shift Type", filters={"name": ["in", sorted(active_names)]}, fields=list(SHIFT_FIELDS))
		if {shift.name for shift in shifts} != set(active_names):
			raise ShiftConfigurationError(_("Salah satu Shift Type aktif outlet tidak ditemukan."))
		local_time = get_datetime(context["evaluated_at"])
		transition_minutes = int(_number(outlet.shift_transition_minutes, _("Jeda Peralihan IN"), integer=True))
		rows = [row for row in (outlet.get("shifts") or []) if row.enabled]

		for shift in shifts:
			_clock(shift.start_time, shift.name)  # reject invalid clocks even when the shift is off today
		windows = shift_windows(rows, shifts, local_time, transition_minutes)
	except ShiftConfigurationError as exc:
		result.update(code="invalid_configuration", message=str(exc))
		return result
	except OverflowError:
		result.update(code="invalid_configuration", message=_("Tanggal kejadian shift berada di luar rentang yang didukung."))
		return result
	result["windows"] = [window.as_dict() for window in windows]
	candidates = [window for window in windows if window.contains(local_time)]
	result["candidates"] = [window.as_dict() for window in candidates]
	if not candidates:
		result.update(code="outside_checkin_window", message=_("Tidak ada shift outlet yang menerima IN pada waktu ini. Periksa jadwal atau hubungi HR."))
		return result
	if len({window.shift_start for window in candidates}) > 1:
		result.update(code="ambiguous_candidate", message=_("Ada lebih dari satu kandidat IN lintas tanggal. Periksa aturan shift malam dengan HR; sistem tidak memilih shift secara sembarang."))
		return result
	selected = candidates[0]
	if len(candidates) > 1:
		result["choices"] = sorted(window.shift for window in candidates)
		if not chosen_shift:
			result.update(code="shift_choice_required", message=_("Ada lebih dari satu shift dengan jam mulai yang sama. Pilih shift Anda sebelum check-in."))
			return result
		if chosen_shift not in result["choices"]:
			result.update(code="invalid_shift_choice", message=_("Shift yang dipilih tidak tersedia untuk waktu check-in ini."))
			return result
		selected = next(window for window in candidates if window.shift == chosen_shift)
	deadline = datetime.combine(selected.shift_end.date(), time(23, 59, 59))
	snapshot = {
		"version": SNAPSHOT_VERSION,
		"attendance_source": "Outlet",
		"employee": employee,
		"company": context["company"],
		"company_source": "Employee",
		"outlet": outlet.name,
		"outlet_modified": str(outlet.modified or ""),
		"holiday_list": outlet.holiday_list,
		"holiday_source": "Outlet",
		"timezone": context["timezone"],
		"shift_transition_minutes": transition_minutes,
		**selected.as_dict(),
		**deepcopy(selected.policy),
		"standard_working_hours": (selected.shift_end - selected.shift_start).total_seconds() / 3600,
		"checkout_deadline": str(deadline),
		"daily_session_limit": 1,
		"missing_checkout_status": "Present",
		"missing_checkout_hours_source": "Locked Shift Allocation",
	}
	result.update(
		matched=True,
		code="matched",
		message=_("Shift outlet berhasil ditentukan."),
		selection=selected.as_dict(),
		checkin_values={
			"attendance_source": "Outlet",
			"outlet_at_checkin": outlet.name,
			"shift": selected.shift,
			"shift_work_date": selected.work_date.isoformat(),
			"shift_start": str(selected.shift_start),
			"shift_end": str(selected.shift_end),
			"shift_actual_start": str(selected.checkin_start),
			"shift_actual_end": str(deadline),
			"checkout_deadline": str(deadline),
			"shift_policy_snapshot": snapshot,
		},
	)
	return result
