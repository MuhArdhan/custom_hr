"""Cocokkan Gaji: compare HR's salary sheet with the draft slips of one Payroll Entry, cell by cell.

The sheet is read in memory and never saved: it holds every employee's salary.
Columns come from Payroll Settings (tab HRM) by letter (the PH sheet's two-row headers put labels and values in
different columns). Taking the Excel value of a cell submits an overwriting Additional Salary for that
component, tagged with the Payroll Entry, and recalculates the slip.
"""

import base64
import io
import json
import re

from collections import Counter
from collections.abc import Callable

import frappe
from frappe import _
from frappe.utils import flt
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

TOLERANCE = 1  # rupiah: the sheet rounds some amounts
HEADER_ROWS = 20  # the key header is searched in this many top rows
COLUMNS = re.compile(r"^[A-Z]{1,3}(\+[A-Z]{1,3})*$")
MATCH_BY_HEADERS = {
	"nip": ("NIP",),
	"name": ("NAMA", "NAMA CREW", "NAMA KARYAWAN"),
}
STOP_HEADERS = {
	"EMAIL",
	"NO REK",
	"BANK",
	"PENGELUARAN PERUSAHAAN",
	"TANGGAL BERGABUNG",
	"MASA KERJA",
	"STATUS PEGAWAI",
}
IGNORED_HEADERS = {
	"NIP",
	"NAMA",
	"NAMA CREW",
	"NAMA KARYAWAN",
	"JABATAN",
	"PENEMPATAN OUTLET",
	"GP + TUNJANGAN TETAP",
	"INCOME",
	"TOTAL",
	"TOTAL POTONGAN",
	"TOTAL GAJI + BPJS",
	"TOTAL DI TERIMA",
	"TOTAL DITERIMA",
	"TOTAL SALARY",
	"TAKE HOME PAY",
	"THP",
	"THR",
	"HK",
	"KEHADIRAN",
	"JAM LEMBUR",
	"JUMLAH TELAT",
	"CADANGAN BPJS",
	"POTONGAN",
	"LEMBUR",
	"BPJS",
	"OVERTIME",
	"TUNJANGAN",
	"ABSEN",
	"EMPLOYE",
	"AKUN IMIN",
	"KETERANGAN",
}
# Ordered aliases per component; entries with '+' are merged only when explicitly handled below.
AUTO_ALIASES = (
	("Gaji Pokok", ("GP", "GAJI POKOK", "POKOK PROPORSIONAL")),
	("Uang Makan", ("UANG MAKAN", "HARIAN PROPORSIONAL")),
	("Tunjangan Transport", ("TUNJANGAN TRANSPORT", "TUNJ TRANSPORT", "TRANSPORT")),
	("Tunjangan Jabatan", ("TUNJANGAN JABATAN", "TUNJ JABATAN", "JABATAN")),
	("Resiko", ("RESIKO", "TUNJANGAN RESIKO")),
	("Tunjangan Tempat Tinggal", ("TEMPAT TINGGAL", "TUNJANGAN TEMPAT TINGGAL")),
	("Alpha", ("ALPHA",)),
	("Terlambat", ("TERLAMBAT", "POTONGAN TELAT", "TELAT")),
	("Tidak Absen In", ("TIDAK ABSEN IN",)),
	("Tidak Absen Out", ("TIDAK ABSEN OUT",)),
	("Kasbon", ("KASBON",)),
	("Pending", ("PENDING",)),
	("Training", ("TRAINING",)),
	("Insentif", ("INSENTIF",)),
	("Vending Mesin", ("VENDING MESIN",)),
	("Bonus Target", ("BONUS TARGET",)),
	("Bonus Performance", ("BONUS PERFORMANCE",)),
	("Pinalty", ("PINALTY", "PENALTY")),
	("BPJS Kesehatan", ("BPJS KS", "BPJS KS 1%", "BPJS KESEHATAN")),
	("BPJS Ketenagakerjaan", ("BPJS KT", "BPJS KT 2%", "BPJS KETENAGAKERJAAN")),
)


def column_groups(rows, period_input: set) -> list:
	"""Mapping rows -> one group per Excel column key; a key may list several columns and several components.

	Only a group of one component outside Input Additional Salary can take the Excel value: a combined
	amount cannot be split, and period input components have their own page.
	"""
	groups = {}
	for row in rows:
		key = re.sub(r"\s", "", row.excel_column or "").upper()
		if not COLUMNS.match(key):
			frappe.throw(_("Kolom Excel {0} tidak valid. Isi huruf kolom, mis. AY, atau AO+AQ untuk menjumlah.").format(row.excel_column or "''"))
		group = groups.setdefault(key, frappe._dict(key=key, indexes=[column_index_from_string(c) - 1 for c in key.split("+")], components=[]))
		group.components.append(row.salary_component)
	for group in groups.values():
		group.editable = len(group.components) == 1 and group.components[0] not in period_input
	return list(groups.values())


def nip_text(value) -> str:
	"""123456.0 (a number cell) and ' 123456 ' both -> '123456'."""
	if isinstance(value, float) and value.is_integer():
		value = int(value)
	return str(value).strip() if value is not None else ""


def name_text(value) -> str:
	"""Normalize employee names across case and extra spaces."""
	return " ".join(str(value).split()).upper() if value is not None else ""


def _resolve_match_by(match_by: str | None) -> tuple[str, Callable[[object], str]]:
	mode = (match_by or "nip").strip().lower()
	if mode not in MATCH_BY_HEADERS:
		frappe.throw(_("Mode pencocokan tidak valid: pilih NIP atau Nama."))
	return mode, (name_text if mode == "name" else nip_text)


def _norm_header(value) -> str:
	if not isinstance(value, str):
		return ""
	return re.sub(r"\s+", " ", value).strip().upper()


def _header_token(text: str) -> str:
	clean = re.sub(r"\([^)]*\)", " ", text or "")
	clean = re.sub(r"[.\-_]+", " ", clean)
	return re.sub(r"\s+", " ", clean).strip().upper()


def _find_key_col(row, mode: str) -> int | None:
	accepted = MATCH_BY_HEADERS[mode]
	return next((i for i, value in enumerate(row) if _norm_header(value) in accepted), None)


def _header_key_row(rows, mode: str) -> tuple[int, int]:
	for idx, row in enumerate(rows[:HEADER_ROWS]):
		key_col = _find_key_col(row, mode)
		if key_col is not None:
			return idx, key_col
	label = _("Nama") if mode == "name" else _("NIP")
	frappe.throw(_("Kolom {0} tidak ditemukan di {1} baris teratas sheet.").format(label, HEADER_ROWS))


def _is_text_only_column(data_rows, col_idx: int) -> bool:
	has_num, has_str = False, False
	for row in data_rows[:25]:
		if col_idx >= len(row):
			continue
		val = row[col_idx]
		if val is None or (isinstance(val, str) and not val.strip()):
			continue
		if isinstance(val, (int, float)) and not isinstance(val, bool):
			has_num = True
			break
		if isinstance(val, str):
			has_str = True
	return has_str and not has_num


def _scan_sheet_headers(rows, hdr_idx: int, key_col: int) -> tuple[list[dict], list[dict]]:
	"""Inspect header rows after key_col, pairing two-column Qty|Rupiah headers onto their value index."""
	lower = rows[hdr_idx]
	upper = rows[hdr_idx - 1] if hdr_idx > 0 else ()
	data_rows = rows[hdr_idx + 1 :]
	width = max(len(lower), len(upper))
	stop_col = width
	for i in range(key_col + 1, width):
		low_tok = _header_token(lower[i] if i < len(lower) and isinstance(lower[i], str) else "")
		up_tok = _header_token(upper[i] if i < len(upper) and isinstance(upper[i], str) else "")
		if low_tok in STOP_HEADERS or up_tok in STOP_HEADERS:
			stop_col = i
			break

	columns, options, skip_next = [], [], False
	for i in range(key_col + 1, stop_col):
		if skip_next:
			skip_next = False
			continue
		low_raw = _norm_header(lower[i] if i < len(lower) else None)
		up_raw = _norm_header(upper[i] if i < len(upper) else None)
		if not low_raw and not up_raw:
			continue

		val_idx = i
		raw_next_low = lower[i + 1] if i + 1 < len(lower) else None
		raw_next_up = upper[i + 1] if i + 1 < len(upper) else None
		next_low = _norm_header(raw_next_low)
		next_up = _norm_header(raw_next_up)
		next_low_blank_or_rp = raw_next_low is None or (isinstance(raw_next_low, str) and (not next_low or next_low.startswith("RP")))
		next_up_blank = raw_next_up is None or (isinstance(raw_next_up, str) and not next_up)
		has_next_sub = i + 1 < stop_col and next_up_blank and next_low_blank_or_rp
		low_tok = _header_token(low_raw)
		up_tok = _header_token(up_raw)
		# Sub-column merge check: only pair i+1 when i is a component header, not a bare category banner.
		if has_next_sub and (low_raw or up_tok.startswith("SHIFT ")):
			val_idx = i + 1
			skip_next = True

		if _is_text_only_column(data_rows, val_idx):
			continue

		letter = get_column_letter(val_idx + 1)
		display = " / ".join(part for part in (up_raw, low_raw, next_low if skip_next and next_low else "") if part)
		options.append({"key": letter, "label": f"{letter} — {display}"})
		columns.append({
			"idx": val_idx,
			"letter": letter,
			"low_raw": low_raw,
			"up_raw": up_raw,
			"low_tok": low_tok,
			"up_tok": up_tok,
			"is_paired": val_idx != i,
		})
	return columns, options


def _overtime_alias_components() -> dict[str, str]:
	"""Resolve default Excel overtime components from active Overtime Types so UI component renames take effect."""
	types = frappe.get_all(
		"Overtime Type",
		filters={"disabled": 0},
		fields=["name", "overtime_salary_component"],
		order_by="name asc",
	)
	earning_comps = set(frappe.get_all("Salary Component", filters={"disabled": 0, "type": "Earning"}, pluck="name"))
	by_name = {t.name: t.overtime_salary_component for t in types if t.overtime_salary_component in earning_comps}
	reg = by_name.get("Lembur PH") or by_name.get("Lembur JKT")
	hol = by_name.get("Lembur Holiday PH") or by_name.get("Lembur Holiday JKT")
	if not hol:
		hol = next((comp for name, comp in by_name.items() if "HOLIDAY" in name.upper()), None)
	if not reg:
		reg = next((comp for name, comp in by_name.items() if "HOLIDAY" not in name.upper() and name not in {"Regular", "Lembur Outlet"}), None)
	outlet = by_name.get("Lembur Outlet") or reg
	return {k: v for k, v in (("reguler", reg), ("holiday", hol), ("outlet", outlet)) if v}


def auto_detect_groups(
	rows,
	match_by: str = "nip",
	slip_components: set | None = None,
	period_input: set | None = None,
	db_components: list[str] | None = None,
	overtime_components: dict[str, str] | None = None,
) -> tuple[list, list[dict]]:
	"""Detect Payroll Match groups from sheet headers across both PH and Outlet layouts."""
	mode, _ = _resolve_match_by(match_by)
	hdr_idx, key_col = _header_key_row(rows, mode)
	cols, options = _scan_sheet_headers(rows, hdr_idx, key_col)
	slip_components = set(slip_components or ())
	period_input = set(period_input or ())
	db_components = list(db_components or ())

	by_tok = {}
	for c in cols:
		# Prefer lower header token (e.g. REGULER), else upper header token (e.g. UANG MAKAN, SHIFT PAGI)
		tok = c["low_tok"] or c["up_tok"]
		if tok:
			by_tok.setdefault(tok, []).append(c)

	def pick(aliases):
		for alias in aliases:
			matches = by_tok.get(_header_token(alias))
			if matches:
				return matches[0]
		return None

	matched_rows = []
	used_letters = set()

	# 1. Overtime: PH sheets split REGULER and HOLIDAY by active Overtime Type components;
	#    Outlet sheets use single LEMBUR column -> Lembur Outlet's component.
	ot_map = overtime_components or {}
	reg_comp = ot_map.get("reguler") or ("Lembur Reguler" if (not db_components or "Lembur Reguler" in db_components) else "Upah Lembur")
	hol_comp = ot_map.get("holiday") or ("Lembur Holiday" if (not db_components or "Lembur Holiday" in db_components) else "Upah Lembur")
	out_comp = ot_map.get("outlet") or reg_comp
	reg = pick(("REGULER",))
	hol = pick(("HOLIDAY",))
	if reg and hol:
		if reg_comp == hol_comp:
			matched_rows.append((f"{reg['letter']}+{hol['letter']}", [reg_comp]))
		else:
			matched_rows.append((reg["letter"], [reg_comp]))
			matched_rows.append((hol["letter"], [hol_comp]))
		used_letters.update((reg["letter"], hol["letter"]))
	else:
		lem = pick(("LEMBUR",))
		if lem:
			matched_rows.append((lem["letter"], [out_comp]))
			used_letters.add(lem["letter"])

	# 2. Shift allowance: PH sheets put SHIFT PAGI / SHIFT SIANG in upper row with RP. values below.
	shift_cols = [c for c in cols if c["up_tok"] in {"SHIFT PAGI", "SHIFT SIANG"} or c["low_tok"] == "TUNJANGAN SHIFT"]
	if shift_cols:
		matched_rows.append(("+".join(c["letter"] for c in shift_cols), ["Tunjangan Shift"]))
		used_letters.update(c["letter"] for c in shift_cols)

	# 3. Izin: Outlet uses "Izin" (Potongan IZIN DLL), PH uses "Potongan Izin" (IZIN).
	izin_col = pick(("POTONGAN IZIN", "POTONGAN IZIN DLL", "IZIN"))
	if izin_col:
		izin_comp = "Izin" if ("Izin" in slip_components and "Potongan Izin" not in slip_components) else "Potongan Izin"
		matched_rows.append((izin_col["letter"], [izin_comp]))
		used_letters.add(izin_col["letter"])

	# 4. Standard single-column aliases
	for comp, aliases in AUTO_ALIASES:
		if db_components and comp not in db_components:
			continue
		hit = pick(aliases)
		if hit and hit["letter"] not in used_letters:
			matched_rows.append((hit["letter"], [comp]))
			used_letters.add(hit["letter"])

	# 5. Fallback combined BPJS if individual KS/KT columns weren't present
	if not any(comps == ["BPJS Kesehatan"] or comps == ["BPJS Ketenagakerjaan"] for _, comps in matched_rows):
		beban = pick(("BEBAN BPJS KARY", "BEBAN BPJS"))
		if beban and beban["letter"] not in used_letters:
			matched_rows.append((beban["letter"], ["BPJS Kesehatan", "BPJS Ketenagakerjaan"]))
			used_letters.add(beban["letter"])

	# 6. Any remaining DB Salary Components matching a sheet header verbatim (after token normalization)
	matched_comps = {comp for _, comps in matched_rows for comp in comps}
	for comp in db_components:
		if comp in matched_comps:
			continue
		tok = _header_token(comp)
		if tok in IGNORED_HEADERS:
			continue
		hit = by_tok.get(tok, [None])[0]
		if hit and hit["letter"] not in used_letters:
			matched_rows.append((hit["letter"], [comp]))
			used_letters.add(hit["letter"])

	groups = []
	for key, comps in matched_rows:
		groups.append(
			frappe._dict(
				key=key,
				indexes=[column_index_from_string(c) - 1 for c in key.split("+")],
				components=comps,
				editable=len(comps) == 1 and comps[0] not in period_input,
			)
		)
	return groups, options


def read_sheet(rows, groups, match_by: str = "nip") -> tuple[dict, list]:
	"""{key: {group key: amount}} from the row under the key header down to the end of the main table."""
	mode, normalize = _resolve_match_by(match_by)
	row_list = list(rows)
	hdr_idx, key_col = _header_key_row(row_list, mode)
	name_col = _find_key_col(row_list[hdr_idx], "name") if mode == "nip" else None

	amounts, duplicates = {}, []
	for row in row_list[hdr_idx + 1 :]:
		key = normalize(row[key_col] if len(row) > key_col else None)
		if mode == "name":
			if not key or key.startswith(("CATATAN", "TOTAL")):
				break
		elif not key:
			name = name_text(row[name_col] if name_col is not None and len(row) > name_col else None)
			if not name or name.startswith(("CATATAN", "TOTAL")):
				break  # below the main table the PH sheet holds notes and other tables
			continue  # one employee has no NIP yet; keep reading employees below
		if key in amounts:
			duplicates.append(key)
		amounts[key] = {g.key: sum(row[i] for i in g.indexes if i < len(row) and isinstance(row[i], (int, float))) for g in groups}
	return amounts, duplicates


def compare_rows(sheet: dict, slips: list, groups: list, match_by: str = "nip") -> frappe._dict:
	"""Rows of the slips with at least one differing cell, plus who is only on one side."""
	mode, normalize = _resolve_match_by(match_by)
	slip_keys = [normalize(slip.employee_name if mode == "name" else slip.nip) for slip in slips]
	duplicate_slips = sorted({k for k, count in Counter(k for k in slip_keys if k).items() if count > 1})
	ambiguous = set(duplicate_slips)
	rows, matched, matched_keys = [], 0, set()
	for slip, key in zip(slips, slip_keys):
		if not key or key in ambiguous:
			continue
		excel = sheet.get(key)
		if excel is None:
			continue
		matched += 1
		matched_keys.add(key)
		cells = {}
		for group in groups:
			system = flt(sum(flt(slip.amounts.get(component)) for component in group.components), 2)
			if abs(system - excel[group.key]) > TOLERANCE:
				cells[group.key] = {"system": system, "excel": excel[group.key]}
		if cells:
			rows.append(frappe._dict(slip=slip.name, employee=slip.employee, employee_name=slip.employee_name, nip=slip.nip, cells=cells))
	return frappe._dict(
		rows=rows,
		matched=matched,
		duplicate_slips=duplicate_slips,
		not_in_slips=sorted(key for key in sheet if key not in matched_keys),
		not_in_excel=[
			frappe._dict(employee=s.employee, employee_name=s.employee_name, nip=s.nip)
			for s, key in zip(slips, slip_keys)
			if key not in matched_keys and key not in ambiguous
		],
	)


def _entry(name: str):
	entry = frappe.get_doc("Payroll Entry", name)
	entry.check_permission("write")
	if not frappe.has_permission("Additional Salary", "submit"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if entry.docstatus != 1:
		frappe.throw(_("Payroll Entry belum disubmit, slip gajinya belum dibuat."))
	return entry


def _groups() -> list:
	rows = frappe.get_cached_doc("Payroll Settings").match_columns
	if not rows:
		frappe.throw(_("Isi dulu tabel Kolom Cocokkan Gaji di Payroll Settings (tab HRM)."))
	return column_groups(rows, set(frappe.get_all("Salary Component", filters={"show_in_period_input": 1}, pluck="name")))


def _slips(entry) -> list:
	slips = frappe.db.sql(
		"""
		SELECT ss.name, ss.employee, ss.employee_name, emp.employee_number AS nip
		FROM `tabSalary Slip` ss JOIN `tabEmployee` emp ON emp.name = ss.employee
		WHERE ss.payroll_entry = %s AND ss.docstatus = 0
		ORDER BY ss.employee_name
		""",
		entry.name,
		as_dict=True,
	)
	amounts = {}
	if slips:
		for row in frappe.get_all("Salary Detail", filters={"parenttype": "Salary Slip", "parent": ["in", [s.name for s in slips]]}, fields=["parent", "salary_component", "amount"]):
			slip = amounts.setdefault(row.parent, {})
			slip[row.salary_component] = slip.get(row.salary_component, 0) + flt(row.amount)
	for slip in slips:
		slip.nip = nip_text(slip.nip)
		slip.amounts = amounts.get(slip.name, {})
	return slips


def _parse_json_arg(value):
	"""Parse a JSON RPC argument; Frappe serializes JS null as an empty string."""
	if not isinstance(value, str):
		return value
	cleaned = value.strip()
	if not cleaned or cleaned.lower() in {"null", "none"}:
		return None
	return json.loads(cleaned)


@frappe.whitelist(methods=["POST"])
def compare(
	payroll_entry: str,
	content: str,
	sheet: str | None = None,
	match_by: str = "nip",
	mapping_mode: str = "auto",
	custom_columns: str | list | None = None,
) -> dict:
	"""content is the .xlsx as base64. Without a sheet name it returns the sheet names to pick from."""
	entry = _entry(payroll_entry)
	mode, _normalize = _resolve_match_by(match_by)
	try:
		book = load_workbook(io.BytesIO(base64.b64decode(content)), read_only=True, data_only=True)
	except Exception:
		frappe.throw(_("File tidak bisa dibaca sebagai Excel (.xlsx)."))
	try:
		if not sheet:
			return {"sheets": book.sheetnames}
		if sheet not in book.sheetnames:
			frappe.throw(_("Sheet {0} tidak ada di file.").format(sheet))
		sheet_rows = list(book[sheet].iter_rows(values_only=True))
	finally:
		book.close()

	slips = _slips(entry)
	period_input = set(frappe.get_all("Salary Component", filters={"show_in_period_input": 1}, pluck="name"))
	header_options = []
	try:
		hdr_idx, key_col = _header_key_row(sheet_rows, mode)
		_, header_options = _scan_sheet_headers(sheet_rows, hdr_idx, key_col)
	except frappe.ValidationError:
		header_options = []

	parsed_custom = _parse_json_arg(custom_columns)
	if parsed_custom:
		rows = [frappe._dict(r) for r in parsed_custom if r.get("excel_column") and r.get("salary_component")]
		groups = column_groups(rows, period_input)
		active_mode = "custom"
	elif (mapping_mode or "auto").strip().lower() == "settings":
		groups = _groups()
		active_mode = "settings"
	else:
		slip_components = {comp for s in slips for comp in s.amounts}
		db_components = frappe.get_all("Salary Component", filters={"disabled": 0}, pluck="name")
		groups, _ = auto_detect_groups(
			sheet_rows,
			match_by=mode,
			slip_components=slip_components,
			period_input=period_input,
			db_components=db_components,
			overtime_components=_overtime_alias_components(),
		)
		active_mode = "auto"

	amounts, duplicates = read_sheet(sheet_rows, groups, match_by=mode)
	duplicates = sorted(set(duplicates))
	for key in duplicates:  # which row is right is HR's call: both are left out and listed
		amounts.pop(key)
	result = compare_rows(amounts, slips, groups, match_by=mode)
	result.duplicates = duplicates
	result.match_by = mode
	result.mapping_mode = active_mode
	result.header_options = header_options
	labels = {g.key: " + ".join(g.components) for g in groups}
	result.columns = [
		{
			"key": g.key,
			"label": labels[g.key],
			"editable": g.editable,
			"component": g.components[0],
			"components": g.components,
		}
		for g in groups
	]
	result.slips = len(slips)
	result.all_components = sorted(
		set(frappe.get_all("Salary Component", filters={"disabled": 0, "show_in_period_input": 0}, pluck="name"))
		- period_input
	)
	return result


@frappe.whitelist(methods=["POST"])
def apply(payroll_entry: str, changes: str | list) -> dict:
	"""Each change is {slip, column, amount, component?}: the Excel amount compare returned for that cell.

	All or nothing, so a refused cell leaves every slip as it was.
	"""
	entry = _entry(payroll_entry)
	changes = _parse_json_arg(changes) or []
	period_input = set(frappe.get_all("Salary Component", filters={"show_in_period_input": 1}, pluck="name"))
	settings_rows = frappe.get_cached_doc("Payroll Settings").match_columns or []
	editable = {g.key: g.components[0] for g in column_groups(settings_rows, period_input) if g.editable} if settings_rows else {}
	slips = {s.name: s for s in frappe.get_all("Salary Slip", filters={"payroll_entry": entry.name, "docstatus": 0}, fields=["name", "employee", "company", "end_date"])}
	touched, cancelled = set(), set()
	for change in changes:
		slip = slips.get(change["slip"])
		component = change.get("component") or editable.get(change["column"])
		amount = flt(change.get("amount"))
		if not slip:
			frappe.throw(_("Slip {0} bukan slip draft Payroll Entry ini.").format(change["slip"]))
		if not component or not frappe.db.exists("Salary Component", component) or component in period_input:
			frappe.throw(_("Kolom {0} tidak bisa diambil dari Excel.").format(change.get("column") or component))
		if amount < 0:
			frappe.throw(_("Nilai Excel {0} untuk {1} minus.").format(component, slip.employee))
		# an earlier Pakai Excel of this entry is replaced, not stacked: native refuses two overwrites
		for name in frappe.get_all("Additional Salary", filters={"docstatus": 1, "employee": slip.employee, "salary_component": component, "ref_doctype": "Payroll Entry", "ref_docname": entry.name}, pluck="name"):
			frappe.get_doc("Additional Salary", name).cancel()
			cancelled.add(name)
		frappe.get_doc(
			{
				"doctype": "Additional Salary",
				"employee": slip.employee,
				"company": slip.company,
				"salary_component": component,
				"amount": amount,
				"payroll_date": slip.end_date,
				"overwrite_salary_structure_amount": 1,
				"ref_doctype": "Payroll Entry",
				"ref_docname": entry.name,
			}
		).submit()
		touched.add(slip.name)
	for name in touched:
		slip = frappe.get_doc("Salary Slip", name)
		for table in ("earnings", "deductions"):  # a row still linked to a cancelled one blocks the save
			slip.set(table, [row for row in slip.get(table) if row.additional_salary not in cancelled])
		slip.save()  # validate recalculates the components with the new Additional Salary
	return {"applied": len(changes), "slips": len(touched)}
