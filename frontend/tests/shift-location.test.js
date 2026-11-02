import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import vm from "node:vm"
import { fileURLToPath } from "node:url"

// The desk script is a plain browser file: load it with just enough of `frappe` for its top level.
const file = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../custom_hr/public/js/shift_location.js")
const handlers = {}
const context = vm.createContext({ frappe: { ui: { form: { on: (doctype, events) => { handlers[doctype] = events } } } } })
vm.runInContext(fs.readFileSync(file, "utf8"), context)
const marker_coordinates = (...args) => JSON.parse(JSON.stringify(context.marker_coordinates(...args)))

const point = (longitude, latitude) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [longitude, latitude] } })
const collection = (...features) => JSON.stringify({ type: "FeatureCollection", features })

test("a marker placed on the map gives its latitude and longitude (GeoJSON stores longitude first)", () => {
	assert.deepEqual(marker_coordinates(collection(point(106.8166, -6.2001))), { latitude: -6.2001, longitude: 106.8166 })
})

test("with the saved point still on the map, the newly placed marker wins", () => {
	assert.deepEqual(marker_coordinates(collection(point(106.8, -6.2), point(110.4, -7.0))), { latitude: -7.0, longitude: 110.4 })
})

test("shapes other than a marker, an empty map or broken text give nothing", () => {
	const polygon = { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] } }
	for (const value of [collection(polygon), collection(), "", null, "{not json"]) {
		assert.equal(context.marker_coordinates(value), null, String(value))
	}
})

test("moving the marker fills Latitude and Longitude, and an unchanged point writes nothing", async () => {
	const writes = []
	const frm = { doc: { latitude: -6.2, longitude: 106.8, geolocation: collection(point(110.4, -7.0)) }, set_value: async (values) => writes.push(values) }
	await handlers["Shift Location"].geolocation(frm)
	assert.deepEqual(JSON.parse(JSON.stringify(writes)), [{ latitude: -7.0, longitude: 110.4 }])

	writes.length = 0
	frm.doc = { latitude: -7.0, longitude: 110.4, geolocation: collection(point(110.4, -7.0)) }
	await handlers["Shift Location"].geolocation(frm)
	assert.deepEqual(writes, [])
})
