"""Early check-out: HR Settings can keep OUT closed until some minutes before the shift ends.

One setting for every shift (Batasi Check-out Sebelum Shift Selesai + the minutes). The app reads the
opening time from the check-in context, and the server refuses an earlier self-service OUT.
"""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, get_datetime


def checkout_opens_at(checkin):
	"""When OUT opens for this IN: its shift end minus the HR Settings minutes. None = any time."""
	shift_end = checkin.get("shift_end")
	if not shift_end:
		return None  # an IN without a shift has no end to count back from
	if not cint(frappe.db.get_single_value("HR Settings", "batasi_checkout_awal")):
		return None
	minutes = cint(frappe.db.get_single_value("HR Settings", "checkout_dibuka_menit"))
	return get_datetime(shift_end) - timedelta(minutes=max(minutes, 0))


def checkout_closed_message(opens) -> str:
	return _("Check-out baru bisa dilakukan mulai pukul {0}.").format(get_datetime(opens).strftime("%H:%M"))


def validate_checkout_open(checkin, time):
	opens = checkout_opens_at(checkin)
	if opens and get_datetime(time) < opens:
		frappe.throw(checkout_closed_message(opens), title=_("Check-out Belum Dibuka"))
