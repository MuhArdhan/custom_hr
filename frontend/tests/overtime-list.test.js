import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs/promises"
import vm from "node:vm"
import dayjs from "dayjs"
import customParseFormat from "dayjs/plugin/customParseFormat.js"

dayjs.extend(customParseFormat)
const source = await fs.readFile(new URL("../../custom_hr/hrm/doctype/overtime_list/overtime_list_list.js", import.meta.url), "utf8")

// The list script with stand-ins for frappe and moment; the user date format is dd-mm-yyyy.
function load() {
	const sandbox = {
		frappe: { listview_settings: {}, datetime: { user_to_obj: value => dayjs(value, "DD-MM-YYYY", true).toDate() } },
		moment: date => ({ format: () => (Number.isNaN(date.getTime()) ? "Invalid date" : dayjs(date).format("YYYY-MM-DD")) }),
		__: value => value,
	}
	vm.runInNewContext(source + "\nglobalThis.oneDateOrRange = one_date_or_range", sandbox)
	return sandbox
}

const frappeParse = value => (value && value.includes(" to ") ? value.split(" to ").map(d => dayjs(d, "DD-MM-YYYY").format("YYYY-MM-DD")) : undefined)

test("a range stays a range", () => {
	const { oneDateOrRange } = load()
	assert.deepEqual([...oneDateOrRange(frappeParse, "01-10-2026 to 15-10-2026")], ["2026-10-01", "2026-10-15"])
})

test("one picked date filters that day only", () => {
	const { oneDateOrRange } = load()
	assert.deepEqual([...oneDateOrRange(frappeParse, "30-10-2026")], ["2026-10-30", "2026-10-30"])
})

test("an empty or unreadable value applies no date filter", () => {
	const { oneDateOrRange } = load()
	assert.equal(oneDateOrRange(frappeParse, ""), undefined)
	assert.equal(oneDateOrRange(frappeParse, "besok"), undefined)
})

test("the field replaces the standard date filter in its old place", () => {
	const sandbox = load()
	const moved = []
	const field = { parse: frappeParse, $wrapper: { insertAfter: target => moved.push(target) } }
	const company = { $wrapper: "company-filter" }
	let added
	sandbox.frappe.listview_settings["Overtime List"].onload({ page: { add_field: df => ((added = df), field), fields_dict: { company } }, filter_area: {} })
	assert.equal(added.fieldtype, "DateRange")
	assert.equal(added.condition, "Between")
	assert.equal(added.default, undefined)  // no prefilled range: looks like the plain date filter
	assert.deepEqual(moved, ["company-filter"])
	assert.deepEqual([...field.parse("30-10-2026")], ["2026-10-30", "2026-10-30"])
})
