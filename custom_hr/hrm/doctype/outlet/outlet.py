# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_time

# Local testing opened explicitly by the user after T11. Each outlet still
# requires its own valid schedule, holiday list and activation timestamp.
OUTLET_AUTO_SHIFT_READY = True

SHIFT_NUMERIC_FIELDS = {
	"begin_check_in_before_shift_start_time": "Batas Datang Awal",
	"allow_check_out_after_shift_end_time": "Buffer Check-out",
	"late_entry_grace_period": "Toleransi Terlambat",
	"early_exit_grace_period": "Toleransi Pulang Awal",
	"working_hours_threshold_for_half_day": "Threshold Half Day",
	"working_hours_threshold_for_absent": "Threshold Absent",
}


class Outlet(Document):
	def validate(self):
		transition = validate_non_negative_number(
			self.get("shift_transition_minutes"), _("Jeda Peralihan IN"), integer=True
		)
		if transition >= 1440:
			frappe.throw(_("Jeda Peralihan IN harus kurang dari 1440 menit (satu hari)."))
		self.shift_transition_minutes = int(transition)
		self.validate_shifts()
		self.validate_auto_shift_activation()
		from custom_hr.services.outlet_location import sync_outlet_location
		sync_outlet_location(self)

	def validate_shifts(self):
		rows = self.get("shifts") or []
		seen = set()
		for row in rows:
			if not row.shift_type:
				frappe.throw(_("Baris {0}: Shift Type wajib diisi.").format(row.idx))
			if row.shift_type in seen:
				frappe.throw(_("Shift Type {0} tercantum lebih dari sekali pada outlet ini.").format(row.shift_type))
			seen.add(row.shift_type)

		if not rows:
			if cint(self.get("enable_outlet_auto_shift")):
				frappe.throw(_("Mode shift otomatis membutuhkan minimal satu shift aktif."))
			return

		shifts = {
			shift.name: shift
			for shift in frappe.get_all(
				"Shift Type",
				filters={"name": ["in", sorted(seen)]},
				fields=["name", "start_time", "end_time", *SHIFT_NUMERIC_FIELDS],
			)
		}
		active_starts = {}
		for row in rows:
			shift = shifts.get(row.shift_type)
			if not shift:
				frappe.throw(_("Shift Type {0} tidak ditemukan.").format(row.shift_type))
			for fieldname, label in SHIFT_NUMERIC_FIELDS.items():
				validate_non_negative_number(shift.get(fieldname), _("{0} pada {1}").format(_(label), shift.name))
			if shift.start_time in (None, "") or shift.end_time in (None, ""):
				frappe.throw(_("Jam mulai dan selesai Shift Type {0} wajib diisi.").format(shift.name))
			start, end = get_time(shift.start_time), get_time(shift.end_time)
			if start == end:
				frappe.throw(_("Jam mulai dan selesai Shift Type {0} tidak boleh sama.").format(shift.name))
			if not cint(row.enabled):
				continue
			if start in active_starts:
				frappe.throw(
					_("Shift aktif {0} dan {1} memiliki jam mulai yang sama. Nonaktifkan salah satunya atau ubah jam mulai.").format(
						active_starts[start], shift.name
					)
				)
			active_starts[start] = shift.name

		if cint(self.get("enable_outlet_auto_shift")) and not active_starts:
			frappe.throw(_("Mode shift otomatis membutuhkan minimal satu shift aktif."))

	def validate_auto_shift_activation(self):
		if not cint(self.get("enable_outlet_auto_shift")):
			return
		if not cint(self.is_active):
			frappe.throw(_("Mode shift otomatis hanya dapat digunakan pada outlet aktif."))
		if not self.holiday_list:
			frappe.throw(_("Pilih Holiday List outlet sebelum mengaktifkan mode shift otomatis."))
		if not self.get("outlet_auto_shift_effective_from"):
			frappe.throw(_("Tanggal mulai mode shift otomatis wajib ditentukan saat aktivasi."))
		if not OUTLET_AUTO_SHIFT_READY:
			frappe.throw(
				_("Mode shift otomatis belum dapat diaktifkan. Integrasi resolver, pairing, dan attendance belum selesai; pengaturan ini masih tahap persiapan."),
				title=_("Aktivasi Belum Tersedia"),
			)


def validate_non_negative_number(value, label: str, *, integer: bool = False) -> Decimal:
	"""Reject invalid/negative input rather than silently coercing it to zero."""
	try:
		number = Decimal(str(value))
	except (InvalidOperation, ValueError, TypeError):
		frappe.throw(_("{0} harus berupa angka tidak negatif.").format(label))
	if not number.is_finite() or number < 0:
		frappe.throw(_("{0} harus berupa angka tidak negatif.").format(label))
	if integer and number != number.to_integral_value():
		frappe.throw(_("{0} harus berupa bilangan bulat menit.").format(label))
	return number
