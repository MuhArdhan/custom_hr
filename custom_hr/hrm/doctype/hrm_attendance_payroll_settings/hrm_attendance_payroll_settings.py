import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate

from custom_hr.api.payroll_attendance import CATEGORIES


class HRMAttendancePayrollSettings(Document):
	def validate(self):
		if not self.company or not self.from_date:
			frappe.throw("Perusahaan dan tanggal mulai berlaku wajib diisi.")
		if self.to_date and getdate(self.to_date) < getdate(self.from_date):
			frappe.throw("Tanggal akhir tidak boleh sebelum tanggal mulai.")
		if not cint(self.disabled):
			filters = {"company": self.company, "disabled": 0,
				"name": ["!=", self.name or ""]}
			for other in frappe.get_all(self.doctype, filters=filters, fields=["name", "from_date", "to_date"]):
				if (getdate(self.from_date) <= getdate(other.to_date or "9999-12-31")
					and getdate(other.from_date) <= getdate(self.to_date or "9999-12-31")):
					frappe.throw("Periode aturan perusahaan bertumpang tindih dengan {0}.".format(other.name))
		if flt(self.late_tolerance_minutes) < 0:
			frappe.throw("Toleransi terlambat tidak boleh negatif.")
		components = {}
		for row in self.rules:
			row.unit = row.unit or "Hari"
			if row.unit not in ("Hari", "Jam"):
				frappe.throw("Satuan harus Hari atau Jam.")
			if row.unit == "Jam":
				if row.category in ("Tidak Absen IN", "Tidak Absen OUT"):
					frappe.throw("Tidak absen IN/OUT belum memiliki sumber durasi; gunakan satuan Hari.")
				if row.category in ("Alpha", "Izin") and flt(row.hours_per_day) <= 0:
					frappe.throw("Isi Jam per Hari untuk konversi Alpha/Izin ke jam.")
			row.company = self.company
			row.from_date = row.from_date or self.from_date
			if getdate(row.from_date) < getdate(self.from_date) or (
				self.to_date and getdate(row.to_date or self.to_date) > getdate(self.to_date)):
				frappe.throw("Periode detail harus berada di dalam periode dokumen.")
			if self.to_date and getdate(row.from_date) > getdate(self.to_date):
				frappe.throw("Tanggal mulai detail melewati akhir periode dokumen.")
			if row.category not in CATEGORIES or not row.from_date:
				frappe.throw("Kategori dan tanggal mulai berlaku wajib diisi.")
			if row.to_date and getdate(row.to_date) < getdate(row.from_date):
				frappe.throw("Tanggal akhir aturan tidak boleh sebelum tanggal mulai.")
			if row.method not in ("Rekap Saja", "Tarif Tetap", "Base / Pembagi"):
				frappe.throw("Metode perhitungan tidak valid.")
			if any(flt(row.get(field)) < 0 for field in ("rate", "divisor", "multiplier")):
				frappe.throw("Tarif, pembagi, dan pengali tidak boleh negatif.")
			if row.salary_component:
				if frappe.db.get_value("Salary Component", row.salary_component, "type") != "Deduction":
					frappe.throw("Komponen presensi harus bertipe Deduction.")
				if row.salary_component in components and components[row.salary_component] != row.category:
					frappe.throw("Satu komponen tidak boleh digunakan oleh dua kategori berbeda.")
				components[row.salary_component] = row.category
			if cint(row.enabled):
				if not row.company:
					frappe.throw("Pilih perusahaan sebelum mengaktifkan estimasi nominal.")
				if not row.salary_component or row.method == "Rekap Saja":
					frappe.throw("Pilih komponen dan metode nominal sebelum mengaktifkan estimasi.")
				if row.method == "Base / Pembagi" and flt(row.divisor) <= 0:
					frappe.throw("Pembagi Base harus lebih dari nol.")
		for index, row in enumerate(self.rules):
			for other in self.rules[index + 1:]:
				if row.category != other.category or row.company != other.company:
					continue
				if (getdate(row.from_date) <= getdate(other.to_date or "9999-12-31")
					and getdate(other.from_date) <= getdate(row.to_date or "9999-12-31")):
					frappe.throw("Periode aturan {0} bertumpang tindih.".format(row.category))
