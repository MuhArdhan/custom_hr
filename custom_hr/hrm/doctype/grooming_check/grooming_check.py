# Copyright (c) 2026, callmevan1120 and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, getdate, now_datetime

from custom_hr.services.grooming import GROOMING_STEPS

REVIEWED = ("Sesuai", "Tidak Sesuai")


class GroomingCheck(Document):
	def validate(self):
		before = None if self.is_new() else self.get_doc_before_save()
		if before:
			self.validate_unchanged(before)  # photos are fixed, so an older record keeps the steps of its day
		else:
			self.validate_photos()
		self.stamp_review(before)

	def validate_photos(self):
		rows = self.get("photos") or []
		if [row.step for row in rows] != [step["key"] for step in GROOMING_STEPS]:
			frappe.throw(_("Grooming harus berisi {0} foto sesuai urutan langkah.").format(len(GROOMING_STEPS)))
		if not all(row.photo for row in rows):
			frappe.throw(_("Setiap langkah grooming harus memiliki foto."))

	def validate_unchanged(self, before):
		"""A submission is final: only the review fields may change."""
		same = (
			self.employee == before.employee
			and getdate(self.grooming_date) == getdate(before.grooming_date)
			and get_datetime(self.submitted_at) == get_datetime(before.submitted_at)
			and (self.shift or None) == (before.shift or None)
			and (self.checkin or None) == (before.checkin or None)
			and [(row.step, row.photo) for row in self.photos] == [(row.step, row.photo) for row in before.photos]
		)
		if not same:
			frappe.throw(_("Karyawan, tanggal, dan foto grooming tidak dapat diubah. Hanya penilaian yang boleh diisi."))

	def stamp_review(self, before):
		self._stamp_pair(
			before, "review_status", "reviewed_by", "reviewed_on",
			is_auto=bool(getattr(self.flags, "auto_review", False)),
		)
		self._stamp_pair(
			before, "nail_review_status", "nail_reviewed_by", "nail_reviewed_on",
			is_auto=False,
		)

	def _stamp_pair(self, before, status_field: str, by_field: str, on_field: str, *, is_auto: bool):
		status = self.get(status_field) or "Menunggu"
		if is_auto:
			self.set(by_field, None)
			self.set(on_field, now_datetime() if status in REVIEWED else None)
		elif status not in REVIEWED:
			self.set(by_field, None)
			self.set(on_field, None)
		elif status != (before.get(status_field) if before else "Menunggu") or not (before and before.get(by_field)):
			self.set(by_field, frappe.session.user)
			self.set(on_field, now_datetime())
