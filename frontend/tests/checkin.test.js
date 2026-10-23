import test from "node:test"
import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { CheckinSubmission, formatSiteDateTime, hasCoordinates, requestUUID, validContext } from "../src/utils/checkin.js"

const ID = "d288162e-b86c-443d-801d-5ccf98d92d84"
const NEXT_ID = "3399e2eb-47b3-4de1-9557-8a56f242ee35"
const result = (log_type = "IN") => ({ name: "SAVED", employee: "EMP", log_type, shift: "Actual Shift", time: "2026-10-15 09:30:00" })
function storage() {
	const values = new Map()
	return { getItem: (key) => values.get(key) || null, setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) }
}
function flow(store = storage()) {
	let n = 0
	return new CheckinSubmission("EMP", store, { randomUUID: () => n++ ? NEXT_ID : ID })
}
const rejected = (status) => Object.assign(new Error("server rejected"), { response: { status } })

test("server wall-clock display does not parse or shift timestamps", () => {
	assert.equal(formatSiteDateTime("2026-10-15T23:59:59.000000"), "2026-10-15 23:59:59")
	assert.equal(formatSiteDateTime("2026-10-16 00:00:00"), "2026-10-16 00:00:00")
	assert.equal(formatSiteDateTime(null), "")
})
test("different browser/host timezones do not change displayed server values or actions", () => {
	const url = new URL("../src/utils/checkin.js", import.meta.url).href
	const code = `import {formatSiteDateTime,validContext} from ${JSON.stringify(url)}; console.log(JSON.stringify([formatSiteDateTime('2026-10-16 00:05:00'),validContext({employee:'EMP',next_action:'OUT',allowed:true},'EMP')]))`
	const outputs = ["UTC", "Pacific/Honolulu", "Asia/Tokyo"].map((TZ) => execFileSync(process.execPath, ["--input-type=module", "-e", code], { env: { ...process.env, TZ }, encoding: "utf8" }))
	assert.equal(new Set(outputs).size, 1)
})
test("coordinates allow a zero axis but reject missing/default/nonfinite values", () => {
	assert.ok(hasCoordinates(0, 110))
	assert.ok(hasCoordinates(-7, 0))
	for (const pair of [[0, 0], [null, 110], ["", 110], [91, 110], [-7, 181], [NaN, 110], [false, 110]]) assert.equal(hasCoordinates(...pair), false)
})
test("only a valid context for the current employee can drive an action", () => {
	assert.ok(validContext({ employee: "EMP", next_action: "OUT", allowed: true }, "EMP"))
	for (const value of [null, { employee: "OTHER", next_action: "IN", allowed: true }, { employee: "EMP", next_action: "GUESS", allowed: true }, { employee: "EMP", next_action: "IN" }]) assert.equal(validContext(value, "EMP"), false)
})
test("secure UUID fallback works without randomUUID on an insecure dev origin", () => {
	assert.equal(requestUUID({ getRandomValues: (bytes) => bytes.fill(0) }), "00000000-0000-4000-8000-000000000000")
	assert.throws(() => requestUUID(null), /Secure/)
})
test("new action has one UUID and only minimal retry metadata is stored", () => {
	const store = storage(), f = flow(store)
	f.begin("IN", "face")
	assert.equal(f.pending.request_id, ID)
	assert.equal(f.begin("OUT", "standard").log_type, "IN")
	assert.deepEqual(Object.keys(JSON.parse(store.getItem(f.key))).sort(), ["channel", "employee", "expected_checkin", "log_type", "request_id", "uncertain", "work_date"])
})
test("successful submission returns the final stored shift and clears pending metadata", async () => {
	const f = flow()
	f.begin("IN", "standard")
	const response = await f.submit(async (payload) => {
		assert.equal(payload.request_id, ID)
		assert.equal(payload.log_type, "IN")
		assert.equal(payload.time, undefined)
		return result()
	}, { latitude: 0, longitude: 110 })
	assert.equal(response.shift, "Actual Shift")
	assert.equal(f.pending, null)
	assert.equal(f.storage.getItem(f.key), null)
	f.begin("OUT", "standard")
	assert.equal(f.pending.request_id, NEXT_ID)
})
test("double click while a POST is in flight sends only one request", async () => {
	const f = flow()
	f.begin("IN", "standard")
	let complete, calls = 0
	const send = () => { calls++; return new Promise((resolve) => { complete = resolve }) }
	const first = f.submit(send, {})
	assert.equal(f.busy, true)
	assert.equal(await f.submit(send, {}), null)
	assert.equal(calls, 1)
	complete(result())
	await first
	assert.equal(f.busy, false)
})
test("lost network response retains the same UUID and bound action", async () => {
	const f = flow()
	f.begin("IN", "standard")
	await assert.rejects(f.submit(async () => { throw new TypeError("network") }, {}))
	assert.equal(f.pending.uncertain, true)
	assert.equal(f.begin("OUT", "face").request_id, ID)
	await f.submit(async (payload) => { assert.equal(payload.log_type, "IN"); assert.equal(payload.request_id, ID); return result() }, {})
})
test("uncertain state survives reload without persisting biometrics or GPS", async () => {
	const store = storage(), f = flow(store)
	f.begin("OUT", "face", { checkin: "ORIGINAL-IN", workDate: "2026-10-15" })
	await assert.rejects(f.submit(async () => { throw new Error("offline") }, { descriptor: [1], photo: "secret", latitude: 1 }))
	const raw = store.getItem(f.key)
	assert.ok(!raw.includes("descriptor") && !raw.includes("photo") && !raw.includes("latitude") && !raw.includes("secret"))
	assert.equal(flow(store).pending.request_id, ID)
})
test("an unsent attempt can be safely cancelled and is not restored as uncertain", () => {
	const store = storage(), f = flow(store)
	f.begin("IN", "standard")
	assert.equal(flow(store).pending, null)
	f.cancelUnsent()
	assert.equal(f.pending, null)
})
test("uncertain attempt cannot be discarded by closing a modal", async () => {
	const f = flow()
	f.begin("IN", "standard")
	await assert.rejects(f.submit(async () => { throw new Error("offline") }, {}))
	f.cancelUnsent()
	assert.equal(f.pending.request_id, ID)
})
test("initial definite validation rejection permits a corrected new attempt", async () => {
	const f = flow()
	f.begin("IN", "face")
	await assert.rejects(f.submit(async () => { throw rejected(417) }, {}))
	assert.equal(f.pending, null)
})
test("rejection of a retry does not prove the original request never committed", async () => {
	const f = flow()
	f.begin("IN", "face")
	await assert.rejects(f.submit(async () => { throw new Error("lost response") }, {}))
	await assert.rejects(f.submit(async () => { throw rejected(417) }, {}))
	assert.equal(f.pending.request_id, ID)
})
test("timeouts, rate limits and server errors retain the retry identity", async () => {
	for (const status of [408, 429, 500, 502]) {
		const f = flow(); f.begin("IN", "standard")
		await assert.rejects(f.submit(async () => { throw rejected(status) }, {}))
		assert.equal(f.pending.request_id, ID)
	}
})
test("read-only recovery confirms a committed action without another POST", async () => {
	const f = flow(); f.begin("IN", "face")
	await assert.rejects(f.submit(async () => { throw new Error("lost response") }, {}))
	const recovered = await f.recover(async (id) => { assert.equal(id, ID); return { ...result(), replayed: true } })
	assert.ok(recovered.replayed)
	assert.equal(f.pending, null)
})
test("not found during recovery is not authorization for a new action", async () => {
	const f = flow(); f.begin("IN", "standard")
	await assert.rejects(f.submit(async () => { throw new Error("network") }, {}))
	assert.equal(await f.recover(async () => null), null)
	assert.equal(f.pending.request_id, ID)
	assert.equal(f.begin("OUT", "standard").log_type, "IN")
})
test("malformed or foreign results cannot clear the uncertain action", async () => {
	for (const response of [null, { ...result(), employee: "OTHER" }, result("OUT")]) {
		const f = flow(); f.begin("IN", "standard")
		await assert.rejects(f.submit(async () => response, {}))
		assert.equal(f.pending.request_id, ID)
	}
})
test("storage is scoped to employee and corrupt metadata cannot submit", () => {
	const store = storage(), f = flow(store)
	store.setItem(f.key, JSON.stringify({ employee: "OTHER", request_id: ID, log_type: "IN", channel: "standard", uncertain: true }))
	assert.equal(flow(store).pending, null)
	store.setItem(f.key, "invalid-json")
	assert.equal(flow(store).pending, null)
})
test("blocked storage fails before a POST can be sent", () => {
	const f = new CheckinSubmission("EMP", { getItem() { throw new Error("blocked") }, setItem() { throw new Error("blocked") } }, { randomUUID: () => ID })
	assert.throws(() => f.begin("IN", "standard"), /session storage is unavailable/)
	assert.equal(f.pending, null)
})

test("OUT retry retains the original IN reference and cannot be redirected by payload", async () => {
	const f = flow(); f.begin("OUT", "standard", { checkin: "ORIGINAL-IN", workDate: "2026-10-15" })
	await assert.rejects(f.submit(async () => { throw new Error("network") }, {}))
	await f.submit(async (params) => { assert.equal(params.expected_checkin, "ORIGINAL-IN"); return result("OUT") }, { expected_checkin: "NEW-IN" })
})

test("OUT without an original IN reference fails before POST", async () => {
	const f = flow(); f.begin("OUT", "standard")
	let calls = 0
	await assert.rejects(f.submit(async () => { calls++; return result("OUT") }, {}), /original IN reference/)
	assert.equal(calls, 0)
})

test("restored metadata is whitelisted and cannot retain extra biometric fields", () => {
	const store = storage(), f = flow(store)
	store.setItem(f.key, JSON.stringify({ employee: "EMP", request_id: ID, log_type: "IN", channel: "face", uncertain: true, descriptor: [1], photo: "secret" }))
	const restored = flow(store)
	assert.equal(restored.pending.request_id, ID)
	assert.equal(restored.pending.descriptor, undefined)
	assert.equal(restored.pending.photo, undefined)
})
