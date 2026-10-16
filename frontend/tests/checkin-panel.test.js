import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs/promises"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { createRequire } from "node:module"
import vm from "node:vm"
import { build } from "esbuild"
import { parse, compileScript } from "@vue/compiler-sfc"
import { createRenderer, defineComponent, h, nextTick, reactive } from "vue"

const require = createRequire(import.meta.url)
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const source = await fs.readFile(path.join(root, "src/components/CheckInPanel.vue"), "utf8")
const { descriptor } = parse(source)
const compiled = compileScript(descriptor, { id: "t11-checkin", inlineTemplate: true })
const mocks = ["frappe-ui", "@ionic/vue", "@/components/FaceCapture.vue", "@/data/settings"]
const bundle = await build({
	stdin: { contents: compiled.content, resolveDir: root, loader: "js" }, bundle: true, write: false, format: "cjs", platform: "node", external: ["vue"],
	plugins: [{ name: "t11-mocks", setup(b) {
		b.onResolve({ filter: /.*/ }, ({ path: name }) => mocks.includes(name) ? { path: name, namespace: "mock" } : name.startsWith("@/") ? { path: path.join(root, "src", name.slice(2) + ".js") } : null)
		b.onLoad({ filter: /.*/, namespace: "mock" }, ({ path: name }) => ({ contents: `module.exports = globalThis.__mocks[${JSON.stringify(name)}]`, loader: "js" }))
	} }],
})
const flush = async () => { for (let i = 0; i < 6; i++) { await new Promise(setImmediate); await nextTick() } }
const ID = "d288162e-b86c-443d-801d-5ccf98d92d84"
const ctx = (changes = {}) => ({ employee: "EMP", next_action: "IN", allowed: true, outlet: "Original Outlet", candidate_shift: "Shift 1", shift_work_date: "2026-10-15", checkout_deadline: "2026-10-15 23:59:59", server_time: "2026-10-15 09:29:59", ...changes })
const saved = () => ({ name: "SAVED", employee: "EMP", log_type: "IN", shift: "Shift 2 FINAL", time: "2026-10-15 09:30:00" })

function mount(options = {}) {
	const calls = [], listeners = new Map(), data = new Map(), toasts = []
	let current = ctx(options.context), failContext = false, lookupResult = null
	let post = options.post || (async () => { current = ctx({ next_action: "OUT", candidate_shift: "Shift 2 FINAL" }); return saved() })
	const request = async (url, params) => {
		calls.push({ url, params })
		if (url.endsWith("get_checkin_context")) { if (failContext) throw new Error("context offline"); return current }
		if (url.endsWith("get_checkin_request_result")) return lookupResult
		if (url.endsWith("get_face_status")) return { enrolled: true }
		if (url.endsWith("validate_checkin_location")) return options.locationCheck ? options.locationCheck(params) : { valid: true }
		return post(params)
	}
	const settings = reactive({ data: { allow_employee_checkin_from_mobile_app: 1, enable_face_checkin: 0, require_face_checkin: 0, allow_geolocation_tracking: 0, ...options.settings } })
	settings.reload = async () => settings.data
	const resource = ({ url }) => {
		const r = reactive({ data: null, loading: false, async fetch(params) { r.loading = true; try { r.data = await request(url, params); return r.data } finally { r.loading = false } } })
		r.submit = r.fetch
		r.reset = () => { r.data = null }
		return r
	}
	const Button = defineComponent({ inheritAttrs: false, props: ["disabled", "loading"], setup(p, { slots, attrs }) { return () => h("button", { ...attrs, disabled: p.disabled, loading: p.loading }, slots.default?.()) } })
	const Modal = defineComponent({ props: ["isOpen", "canDismiss"], setup(p, { slots }) { return () => p.isOpen ? h("modal", {}, slots.default?.()) : null } })
	const Face = defineComponent({ setup(_, { emit }) { return () => h("face", { onClick: () => emit("captured", { descriptors: [[0]], photo: "temporary-photo" }) }) } })
	const storage = { getItem: (k) => data.get(k) || null, setItem: (k, v) => data.set(k, v), removeItem: (k) => data.delete(k) }
	const window = { sessionStorage: storage, crypto: { randomUUID: () => ID }, setInterval() { return 1 }, clearInterval() {}, addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: (name) => listeners.delete(name) }
	const document = { visibilityState: "visible", addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: (name) => listeners.delete(name) }
	let gpsCalls = 0
	const navigator = { onLine: true, geolocation: { getCurrentPosition(success) { gpsCalls++; success({ coords: { latitude: 0, longitude: 110 } }) } } }
	const module = { exports: {} }
	const sandbox = { module, exports: module.exports, require, console, window, navigator, document,
		__mocks: {
			"frappe-ui": { createResource: resource, createListResource: () => reactive({ data: [], async reload() { return [] } }), FeatherIcon: "span", toast: (v) => toasts.push(v) },
			"@ionic/vue": { IonModal: Modal }, "@/components/FaceCapture.vue": Face, "@/data/settings": { settings },
		},
	}
	vm.runInNewContext(bundle.outputFiles[0].text, sandbox)
	const detach = (node) => { if (node.parent) { const i = node.parent.children.indexOf(node); if (i >= 0) node.parent.children.splice(i, 1) } }
	const renderer = createRenderer({
		createElement: (type) => ({ type, children: [], props: {}, text: "" }), createText: (text) => ({ type: "text", text }), createComment: (text) => ({ type: "comment", text }),
		setText: (n, text) => { n.text = text }, setElementText: (n, text) => { n.text = text; n.children = [] },
		patchProp: (n, key, _, value) => { n.props[key] = value }, insert: (n, p, anchor) => { detach(n); n.parent = p; const index = anchor ? p.children.indexOf(anchor) : -1; if (index < 0) p.children.push(n); else p.children.splice(index, 0, n) }, remove: detach,
		parentNode: (n) => n.parent, nextSibling: (n) => n.parent?.children[n.parent.children.indexOf(n) + 1] || null,
	})
	const host = { children: [] }, app = renderer.createApp(module.exports.default)
	const employee = reactive({ data: { name: "EMP", first_name: "Test" } })
	app.component("Button", Button)
	app.component("router-link", defineComponent({ setup(_, { slots }) { return () => h("a", {}, slots.default?.()) } }))
	app.provide("$employee", employee)
	app.provide("$socket", { emit() {}, on: (event, fn) => listeners.set(`socket:${event}`, fn), off: (event) => listeners.delete(`socket:${event}`) })
	app.provide("$translate", (text, args = []) => text.replace(/\{(\d+)\}/g, (_, i) => args[i]))
	app.mount(host)
	const text = (n = host) => n.type === "comment" ? "" : (n.text || "") + (n.children || []).map((c) => text(c)).join(" ")
	const nodes = (type, n = host) => [...(n.type === type ? [n] : []), ...(n.children || []).flatMap((c) => nodes(type, c))]
	return { calls, listeners, data, toasts, employee, settings, text, nodes, get gpsCalls() { return gpsCalls }, setContext: (v) => { current = v }, failContext: () => { failContext = true }, setLookup: (v) => { lookupResult = v }, setPost: (v) => { post = v }, click(label) { const n = nodes("button").find((b) => text(b).trim() === label); assert.ok(n, `Missing button ${label}: ${text()}`); if (!n.props.disabled) return n.props.onClick?.() }, unmount: () => app.unmount() }
}

test("location is checked before confirmation and outside radius disables submit until retry succeeds", async () => {
	let allowed = false
	const ui = mount({ settings: { allow_geolocation_tracking: 1 }, locationCheck: async () => {
		if (!allowed) throw new Error("Outside outlet radius")
		return { valid: true }
	} })
	try {
		await flush(); await ui.click("Check In"); await flush()
		assert.match(ui.text(), /Outside outlet radius/)
		assert.equal(ui.nodes("button").find(b => ui.text(b).trim() === "Confirm Check In").props.disabled, true)
		assert.equal(ui.calls.filter(c => c.url.endsWith("submit_checkin")).length, 0)
		allowed = true
		await ui.click("Retry location"); await flush()
		assert.match(ui.text(), /Location verified/)
		assert.equal(ui.nodes("button").find(b => ui.text(b).trim() === "Confirm Check In").props.disabled, false)
		const checks = ui.calls.filter(c => c.url.endsWith("validate_checkin_location"))
		assert.equal(checks.length, 2)
		assert.equal(checks[0].params.latitude, 0)
		assert.equal(checks[0].params.log_type, "IN")
	} finally { ui.unmount() }
})

test("pending location validation blocks confirmation and late responses cannot validate a reopened modal", async () => {
	const resolves = []
	const ui = mount({ settings: { allow_geolocation_tracking: 1 }, locationCheck: () => new Promise(resolve => resolves.push(resolve)) })
	try {
		await flush(); await ui.click("Check In"); await flush()
		assert.match(ui.text(), /Checking location/)
		assert.equal(ui.nodes("button").find(b => ui.text(b).trim() === "Confirm Check In").props.disabled, true)
		await ui.click("Close"); await ui.click("Check In"); await flush()
		resolves[0]({ valid: true }); await flush()
		assert.equal(ui.nodes("button").find(b => ui.text(b).trim() === "Confirm Check In").props.disabled, true)
		resolves[1]({ valid: true }); await flush()
		assert.equal(ui.nodes("button").find(b => ui.text(b).trim() === "Confirm Check In").props.disabled, false)
	} finally { ui.unmount() }
})

test("location preflight sends original IN reference for checkout", async () => {
	const ui = mount({ context: { next_action: "OUT", paired_checkin: "IN-ORIGINAL" }, settings: { allow_geolocation_tracking: 1 } })
	try {
		await flush(); await ui.click("Check Out"); await flush()
		const call = ui.calls.find(c => c.url.endsWith("validate_checkin_location"))
		assert.equal(call.params.expected_checkin, "IN-ORIGINAL")
		assert.equal(call.params.log_type, "OUT")
	} finally { ui.unmount() }
})

test("component uses backend context and shows outlet and shift", async () => {
	const ui = mount(); try { await flush(); assert.match(ui.text(), /Original Outlet/); assert.match(ui.text(), /Shift 1/); assert.ok(ui.calls.some((c) => c.url.endsWith("get_checkin_context"))) } finally { ui.unmount() }
})

test("panel retains outlet and shift while compact modal omits both", async () => {
	const ui = mount(); try {
		await flush()
		assert.equal(ui.nodes("details").length, 0)
		assert.ok(!ui.text().includes("Attendance details"))
		assert.match(ui.text(), /Original Outlet/)
		assert.match(ui.text(), /Shift 1/)
		await ui.click("Check In"); await flush()
		const modalText = ui.text(ui.nodes("modal")[0])
		assert.ok(!modalText.includes("Original Outlet"))
		assert.ok(!modalText.includes("Shift 1"))
		assert.ok(!modalText.includes("Outlet:"))
		assert.ok(!modalText.includes("Shift:"))
		for (const label of ["Work Date", "Check-out Deadline", "Server time", "Candidate Shift", "Locked Shift"]) assert.ok(!modalText.includes(label))
	} finally { ui.unmount() }
})
test("blocked backend context disables IN and displays its reason", async () => {
	const ui = mount({ context: { allowed: false, message: "Integration not ready" } }); try { await flush(); assert.match(ui.text(), /Integration not ready/); await ui.click("Check In"); assert.equal(ui.nodes("modal").length, 0) } finally { ui.unmount() }
})
test("completed session hides the double-shift explanation but keeps attendance disabled", async () => {
	const message = "Anda sudah memiliki check-in pada tanggal kerja ini. Double shift tidak diperbolehkan."
	const ui = mount({ context: { next_action: "DONE", allowed: false, reason: "session_complete_or_expired", message } }); try {
		await flush()
		assert.ok(!ui.text().includes(message))
		assert.match(ui.text(), /Attendance Completed/)
		await ui.click("Attendance Completed")
		assert.equal(ui.nodes("modal").length, 0)
	} finally { ui.unmount() }
})

test("native mode without a shift does not display a fictitious shift", async () => {
	const ui = mount({ context: { mode: "Native", candidate_shift: null } }); try { await flush(); assert.match(ui.text(), /Original Outlet/); assert.ok(!ui.text().includes("Shift 1")) } finally { ui.unmount() }
})
test("camera-open preview is not submitted as shift or browser timestamp", async () => {
	const ui = mount(); try {
		await flush(); await ui.click("Check In"); await flush(); assert.equal(ui.gpsCalls, 0)
		await ui.click("Confirm Check In"); await flush()
		const post = ui.calls.find((c) => c.url.endsWith("submit_checkin")); assert.ok(post); assert.equal(post.params.request_id, ID); assert.equal(post.params.time, undefined); assert.equal(post.params.shift, undefined)
		assert.match(ui.text(), /Shift 2 FINAL/); assert.equal(ui.nodes("modal").length, 0)
	} finally { ui.unmount() }
})
test("incomplete session warning comes from server, not a browser date comparison", async () => {
	const ui = mount({ context: { incomplete_session: { shift_work_date: "2026-10-14", message: "Contact HR; OUT remains empty" } } }); try { await flush(); assert.match(ui.text(), /Missing Check-out/); assert.match(ui.text(), /OUT remains empty/) } finally { ui.unmount() }
})
test("failed context refresh removes a stale enabled action", async () => {
	const ui = mount(); try { await flush(); ui.failContext(); ui.listeners.get("online")(); await flush(); assert.match(ui.text(), /context offline/); await ui.click("Check In"); assert.equal(ui.nodes("modal").length, 0) } finally { ui.unmount() }
})
test("uncertain POST recovers on reconnect without turning retry into a new OUT", async () => {
	const ui = mount({ post: async () => { throw new TypeError("lost response") } }); try {
		await flush(); await ui.click("Check In"); await flush(); await ui.click("Confirm Check In"); await flush()
		assert.match(ui.text(), /previous request is not confirmed/)
		ui.setLookup({ ...saved(), replayed: true }); ui.setContext(ctx({ next_action: "OUT", candidate_shift: "Shift 2 FINAL" }))
		await ui.listeners.get("online")(); await flush()
		assert.equal(ui.calls.filter((c) => c.url.endsWith("submit_checkin")).length, 1); assert.equal(ui.nodes("modal").length, 0); assert.ok(!ui.text().includes("Saved IN")); assert.match(ui.text(), /Shift 2 FINAL/)
	} finally { ui.unmount() }
})
test("geolocation disabled does not request device permission; a zero latitude works when enabled", async () => {
	const ui = mount({ settings: { allow_geolocation_tracking: 1 } }); try { await flush(); await ui.click("Check In"); await flush(); assert.equal(ui.gpsCalls, 1); await ui.click("Confirm Check In"); await flush(); assert.equal(ui.calls.find((c) => c.url.endsWith("submit_checkin")).params.latitude, 0) } finally { ui.unmount() }
})
test("switching employee while mounted removes the stale modal and cannot submit", async () => {
	const ui = mount(); try { await flush(); await ui.click("Check In"); await flush(); ui.employee.data.name = "OTHER"; await flush(); assert.equal(ui.nodes("modal").length, 0); assert.equal(ui.calls.filter((c) => c.url.endsWith("submit_checkin")).length, 0) } finally { ui.unmount() }
})
test("component removes only its own subscriptions on unmount", async () => {
	const ui = mount(); await flush(); ui.unmount(); assert.equal(ui.listeners.size, 0)
})

test("face capture uses the shared face endpoint only after explicit confirmation", async () => {
	const ui = mount({ settings: { require_face_checkin: 1 } }); try {
		await flush(); await ui.click("Check In"); await flush()
		assert.equal(ui.nodes("face").length, 1)
		ui.nodes("face")[0].props.onClick(); await flush()
		assert.equal(ui.calls.filter((c) => c.url.endsWith("face_checkin")).length, 0)
		await ui.click("Confirm Check In"); await flush()
		const post = ui.calls.find((c) => c.url.endsWith("face_checkin")); assert.ok(post); assert.equal(post.params.request_id, ID); assert.equal(post.params.descriptor, "[0]")
		assert.equal(ui.gpsCalls, 0)
	} finally { ui.unmount() }
})

test("component blocks duplicate confirmation while a POST is in flight", async () => {
	let complete
	const ui = mount({ post: () => new Promise((resolve) => { complete = resolve }) }); try {
		await flush(); await ui.click("Check In"); await flush()
		const first = ui.click("Confirm Check In"); await flush()
		ui.click("Confirm Check In")
		assert.equal(ui.calls.filter((c) => c.url.endsWith("submit_checkin")).length, 1)
		complete(saved()); await first; await flush()
	} finally { ui.unmount() }
})

test("opening a retry that was already committed does not open a new OUT modal", async () => {
	const ui = mount({ post: async () => { throw new Error("lost response") } }); try {
		await flush(); await ui.click("Check In"); await flush(); await ui.click("Confirm Check In"); await flush(); await ui.click("Close"); await flush()
		ui.setLookup(saved()); ui.setContext(ctx({ next_action: "OUT", paired_checkin: "SAVED" }))
		await ui.click("Retry IN"); await flush()
		assert.equal(ui.nodes("modal").length, 0)
		assert.equal(ui.calls.filter((c) => c.url.endsWith("submit_checkin")).length, 1)
	} finally { ui.unmount() }
})

test("OUT confirmation sends the original IN identity as a backend precondition", async () => {
	const ui = mount({ context: { next_action: "OUT", paired_checkin: "ORIGINAL-IN" }, post: async (params) => ({ ...saved(), log_type: "OUT", paired_checkin: params.expected_checkin }) }); try {
		await flush(); await ui.click("Check Out"); await flush(); await ui.click("Confirm Check Out"); await flush()
		assert.equal(ui.calls.find((c) => c.url.endsWith("submit_checkin")).params.expected_checkin, "ORIGINAL-IN")
	} finally { ui.unmount() }
})

test("overnight session shows server work date and deadline without moving to browser's day", async () => {
	const ui = mount({ context: { next_action: "OUT", paired_checkin: "NIGHT-IN", shift_work_date: "2026-10-15", server_time: "2026-10-16 02:00:00", checkout_deadline: "2026-10-16 23:59:59" } }); try {
		await flush(); assert.match(ui.text(), /Shift 1/); assert.match(ui.text(), /Check Out/); assert.ok(!ui.text().includes("Work Date"))
	} finally { ui.unmount() }
})

test("offline event disables opening and online event refreshes context", async () => {
	const ui = mount(); try {
		await flush(); ui.listeners.get("offline")(); await flush(); await ui.click("Check In"); assert.equal(ui.nodes("modal").length, 0)
		const count = ui.calls.length; ui.listeners.get("online")(); await flush(); assert.ok(ui.calls.length > count)
	} finally { ui.unmount() }
})

test("definitive validation error remains visible after the modal closes", async () => {
	const error = Object.assign(new Error("GPS missing"), { response: { status: 417 }, messages: ["GPS missing"] })
	const ui = mount({ post: async () => { throw error } }); try {
		await flush(); await ui.click("Check In"); await flush(); await ui.click("Confirm Check In"); await flush()
		assert.match(ui.text(), /GPS missing/); assert.equal(ui.nodes("modal").length, 0)
	} finally { ui.unmount() }
})
