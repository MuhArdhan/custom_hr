"""Mark standard taxable Earning components with is_tax_applicable = 1 once for PPh 21 TER."""

import frappe

TAXABLE_EARNINGS = (
	"Gaji Pokok",
	"Tunjangan Jabatan",
	"Tunjangan Transport",
	"Resiko",
	"Tunjangan Shift",
	"Tunjangan Harian",
	"Tunjangan Tempat Tinggal",
	"Tunjangan Tetap",
	"Uang Makan",
	"Harian Proporsional",
	"Upah Lembur",
	"Lembur",
	"Lembur Driver",
	"Lembur Reguler",
	"Lembur Holiday",
	"Gaji Harian",
	"Bonus Performance",
	"Bonus Target",
	"Insentif",
	"Training",
	"Vending Mesin",
)


def execute():
	for name in TAXABLE_EARNINGS:
		if frappe.db.exists("Salary Component", name):
			frappe.db.set_value("Salary Component", name, "is_tax_applicable", 1, update_modified=False)
