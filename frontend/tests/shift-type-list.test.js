import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import vm from "node:vm"
import { fileURLToPath } from "node:url"

// The desk script is a plain browser file: load it with just enough of `frappe` for its top level.
const file = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../custom_hr/public/js/shift_type_list.js")
const context = vm.createContext({ frappe: { listview_settings: {}, utils: { escape_html: (value) => value } }, __: (text) => text })
vm.runInContext(fs.readFileSync(file, "utf8"), context)
// arrays built inside the vm context have another prototype; compare plain copies
const outlet_groups = (...args) => JSON.parse(JSON.stringify(context.outlet_groups(...args)))

const initial = { A: true, B: true, C: false, D: false }

test("untouched dialog: the outlets that already have the shift are listed as connected", () => {
	const groups = outlet_groups(initial, new Set(["A", "B"]))
	assert.deepEqual(groups.connected, ["A", "B"])
	assert.deepEqual(groups.add, [])
	assert.deepEqual(groups.remove, [])
})

test("ticking an outlet adds it, unticking a connected one removes it", () => {
	const groups = outlet_groups(initial, new Set(["A", "C"]))
	assert.deepEqual(groups.connected, ["A"])
	assert.deepEqual(groups.add, ["C"])
	assert.deepEqual(groups.remove, ["B"])
})

test("every outlet lands in exactly one place: connected, added, removed or left out", () => {
	const selected = new Set(["B", "D"])
	const { connected, add, remove } = outlet_groups(initial, selected)
	assert.deepEqual([...connected, ...add].sort(), [...selected].sort())
	assert.deepEqual(remove, ["A"])
})

test("with nothing loaded there is nothing to show", () => {
	assert.deepEqual(outlet_groups({}, new Set()), { connected: [], add: [], remove: [] })
})
