import assert from "node:assert/strict"
import { beforeEach, test } from "node:test"

const values = new Map()
globalThis.localStorage = {
	getItem: (key) => values.get(key) ?? null,
	setItem: (key, value) => values.set(key, value),
}
globalThis.window = { frappe: { boot: { __messages: { Employee: "Karyawan" } } }, location: { reload() {} } }

const { __, getLanguage, setLanguage, translationsPlugin, LANGUAGE_KEY } = await import("../src/plugins/translationsPlugin.js")
await translationsPlugin.isReady()

beforeEach(() => values.clear())

test("Indonesian is the app default with local terms and Frappe fallback", () => {
	assert.equal(getLanguage(), "id")
	assert.equal(__("Upcoming Shifts"), "Shift Mendatang")
	assert.equal(__("Employee"), "Karyawan")
	assert.equal(__("Maximum {0} hours for {1}.", [2, "Lembur"]), "Maksimal 2 jam untuk Lembur.")
	assert.equal(__("SOP Grooming"), "SOP Grooming")
	assert.equal(__("Grooming closed"), "Grooming ditutup")
	assert.equal(__("Leaves"), "Izin")
	assert.equal(__("Request Leave"), "Ajukan Izin")
	assert.equal(__("On Leave"), "Sedang Izin")
})

test("English preference keeps source strings and their placeholders", () => {
	values.set(LANGUAGE_KEY, "en")
	assert.equal(__("Upcoming Shifts"), "Upcoming Shifts")
	assert.equal(__("Employee"), "Employee")
	assert.equal(__("Maximum {0} hours for {1}.", [2, "Overtime"]), "Maximum 2 hours for Overtime.")
})

test("language choice is persisted and reloads the app", () => {
	let reloaded = false
	window.location.reload = () => { reloaded = true }
	setLanguage("en")
	assert.equal(values.get(LANGUAGE_KEY), "en")
	assert.equal(reloaded, true)
})
