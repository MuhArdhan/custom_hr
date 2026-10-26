"""Hours-and-minutes text on Attendance for working time, late entry and early exit."""

from datetime import timedelta

import frappe
from frappe.utils import flt, get_datetime


def format_duration(minutes):
	hours, minutes = divmod(int(minutes), 60)
	return " ".join(part for part in (hours and f"{hours} hr", minutes and f"{minutes} min") if part) or "0 min"


def shift_bounds(doc):
	times = doc.shift and frappe.db.get_value("Shift Type", doc.shift, ["start_time", "end_time"])
	if not times:
		return None, None
	day = get_datetime(doc.attendance_date)
	start, end = day + times[0], day + times[1]
	if end <= start:  # shift ends after midnight
		end += timedelta(days=1)
	return start, end


def _minutes(later, earlier):
	return int((later - earlier).total_seconds() // 60)


def fill_durations(doc, method=None):
	"""validate: measured against the shift's own start/end, so grace periods only decide the checkbox."""
	start, end = shift_bounds(doc)
	late = doc.late_entry and start and doc.in_time and _minutes(get_datetime(doc.in_time), start)
	early = doc.early_exit and end and doc.out_time and _minutes(end, get_datetime(doc.out_time))
	# Working Hours is rounded to 2 decimals, so a very short visit is 0 even though both punches exist
	doc.working_duration = format_duration(round(flt(doc.working_hours) * 60)) if doc.working_hours else ("0 min" if doc.in_time and doc.out_time else "")
	if doc.in_time and not doc.out_time:
		doc.missing_checkout = 1  # the Tidak OUT filter then covers native and Department days too
	doc.late_entry_duration = format_duration(late) if late and late > 0 else ""
	doc.early_exit_duration = format_duration(early) if early and early > 0 else ""
