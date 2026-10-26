# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

from frappe.model.document import Document

# Options of the Hari column (outlet_shift.json); each must parse with services.outlet_shift.parse_days
DAY_PRESETS = ("Setiap hari", "Senin-Jumat", "Senin-Kamis", "Jumat", "Senin-Sabtu", "Sabtu-Minggu", "Sabtu", "Minggu", "Senin", "Selasa", "Rabu", "Kamis")


class OutletShift(Document):
	pass
