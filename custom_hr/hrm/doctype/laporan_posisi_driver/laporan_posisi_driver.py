# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class LaporanPosisiDriver(Document):
	def validate(self):
		self.maps_url = maps_url(self.latitude, self.longitude)


def maps_url(latitude, longitude):
	return f"https://www.google.com/maps?q={latitude},{longitude}" if latitude is not None and longitude is not None else None
