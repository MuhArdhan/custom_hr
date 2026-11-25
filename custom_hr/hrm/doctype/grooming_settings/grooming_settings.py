# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

THRESHOLD_FIELDS = (
	"hat_threshold",
	"apron_threshold",
	"shoes_threshold",
	"jeans_threshold",
	"crocs_threshold",
)


class GroomingSettings(Document):
	def validate(self):
		for fieldname in THRESHOLD_FIELDS:
			raw = self.get(fieldname)
			if raw is None or raw == "":
				continue
			value = flt(raw)
			if value <= 0 or value > 1:
				label = self.meta.get_label(fieldname) or fieldname
				frappe.throw(_("{0} harus berada di antara 0 dan 1.").format(label))
