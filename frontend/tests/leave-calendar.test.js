import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs/promises"
import vm from "node:vm"
import dayjs from "dayjs"

const source = await fs.readFile(new URL("../../custom_hr/hrm/page/leave_calendar/leave_calendar.js", import.meta.url), "utf8")
const escape = value => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;")

function calendar() {
	let html = "", text = ""
	const alerts = []
	const wrapper = { html: value => { html = value }, text: value => { text = value }, find: () => ({ prop() {} }) }
	const frappe = { pages: { "leave-calendar": {} }, utils: { escape_html: escape }, datetime: { get_today: () => "2026-10-22" }, call: async () => ({}), show_alert: value => alerts.push(value) }
	const sandbox = { frappe, __: value => value }
	vm.runInNewContext(source + "\nglobalThis.Calendar = LeaveCalendar", sandbox)
	const instance = Object.create(sandbox.Calendar.prototype)
	instance.page = { main: { find: () => wrapper } }
	instance.month = { month: () => 9 }
	instance.filters = {}
	const dialog = { fields_dict: { body: { $wrapper: wrapper } }, approval_date: "2026-10-22", approval_filters: {} }
	return { instance, dialog, frappe, alerts, html: () => html, text: () => text }
}

const item = () => ({ doctype: "Leave Application", kind: "leave", name: "LEAVE-1", status: "Open", calendar_status: "leave_request", modified: "STAMP", employees: [{ employee: "EMP", employee_name: "Employee" }], details: "Annual Leave", description: "Reason", from_date: "2026-10-22", to_date: "2026-10-23", actions: [{ action: "Approve", kind: "approve", next_state: "Approved" }, { action: "Reject", kind: "reject", next_state: "Rejected" }] })

test("day dialog lists applicants and both available decision buttons", async () => {
	const ui = calendar()
	ui.instance.request = async () => ({ items: [item()] })
	await ui.instance.load_day(ui.dialog)
	assert.match(ui.html(), /Employee/)
	assert.match(ui.html(), /Approve/)
	assert.match(ui.html(), /Reject/)
	assert.match(ui.html(), /data-index="0" data-action="1"/)
	assert.equal(ui.dialog.approval_items.length, 1)
})

test("calendar renders six weeks with leave and overtime badges", () => {
	const ui = calendar()
	ui.instance.month = dayjs("2026-10-01")
	ui.instance.render(dayjs("2026-09-27"), { "2026-10-22": { leave: 3, leave_request: 2, approved_leave: 1, overtime: 3 } })
	assert.equal((ui.html().match(/class="ac-day /g) || []).length, 42)
	assert.equal((ui.html().match(/class="ac-weekday"/g) || []).length, 7)
	assert.match(ui.html(), /ac-current/)
	assert.match(ui.html(), /Leave Request \(2\)/)
	assert.match(ui.html(), /Leave \(1\)/)
	assert.match(ui.html(), /Overtime \(3\)/)
	assert.match(ui.html(), /data-date="2026-10-22" data-kind="overtime"/)
	assert.match(ui.html(), /data-date="2026-10-22" data-kind="leave"/)
})

test("untrusted employee names, reasons, status and document identifiers are escaped", async () => {
	const ui = calendar()
	const unsafe = '<img src=x onerror="attack()">'
	const row = { ...item(), name: unsafe, status: unsafe, description: unsafe, employees: [{ employee: unsafe, employee_name: unsafe }] }
	ui.instance.request = async () => ({ items: [row] })
	await ui.instance.load_day(ui.dialog)
	assert.ok(!ui.html().includes("<img"))
	assert.ok(ui.html().includes("&lt;img"))
})

test("day dialog shows the remaining leave balance and flags a request that exceeds it", async () => {
	const ui = calendar()
	ui.instance.request = async () => ({ items: [
		{ ...item(), name: "OK", leave_balance: 8.5, exceeds_balance: false },
		{ ...item(), name: "OVER", leave_balance: 2, exceeds_balance: true },
	] })
	await ui.instance.load_day(ui.dialog)
	assert.match(ui.html(), /Remaining balance: <b>8\.5<\/b> days/)
	assert.match(ui.html(), /Remaining balance: <b>2<\/b> days · request exceeds remaining balance/)
	assert.equal((ui.html().match(/ac-over/g) || []).length, 1)
})

test("leave without pay says it uses no entitlement, and an old server response shows no balance line", async () => {
	const ui = calendar()
	ui.instance.request = async () => ({ items: [{ ...item(), name: "LWP", leave_balance: null }] })
	await ui.instance.load_day(ui.dialog)
	assert.match(ui.html(), /No entitlement \(leave without pay\)/)
	ui.instance.request = async () => ({ items: [item()] })
	await ui.instance.load_day(ui.dialog)
	assert.ok(!ui.html().includes("ac-balance"))
})

test("the whole reason is rendered, not a shortened copy, and stays escaped", async () => {
	const ui = calendar()
	const reason = "Menghadiri pernikahan saudara di luar kota, " .repeat(6) + "<b>x</b>"
	ui.instance.request = async () => ({ items: [{ ...item(), description: reason }] })
	await ui.instance.load_day(ui.dialog)
	assert.ok(ui.html().includes(reason.replace("<b>x</b>", "&lt;b&gt;x&lt;/b&gt;")))
	assert.ok(!ui.html().includes("<b>x</b>"))
})

test("empty day explicitly says no pending requests", async () => {
	const ui = calendar()
	ui.instance.request = async () => ({ items: [] })
	await ui.instance.load_day(ui.dialog)
	assert.match(ui.text(), /There are no requests/)
})

test("compact table uses one row per employee rather than large request cards", async () => {
	const ui = calendar()
	ui.instance.request = async () => ({ items: Array.from({ length: 40 }, (_, i) => ({ ...item(), employee: `EMP-${i}`, employees: [{ employee: `EMP-${i}`, employee_name: `Person ${i}` }] })) })
	await ui.instance.load_day(ui.dialog)
	assert.match(ui.html(), /<table class="table ac-table">/)
	assert.equal((ui.html().match(/<tr>/g) || []).length, 41)
	assert.ok(!ui.html().includes("<section"))
	assert.equal((ui.html().match(/ac-decision/g) || []).length, 80)
})

test("duplicate decisions cannot send multiple posts and only server-approved action name is sent", async () => {
	const ui = calendar()
	const calls = []
	let resolve
	ui.frappe.call = args => { calls.push(args); return new Promise(done => { resolve = done }) }
	ui.instance.load = async () => {}
	ui.instance.load_day = async () => {}
	const row = item()
	const pending = ui.instance.decide(ui.dialog, row, row.actions[0])
	await ui.instance.decide(ui.dialog, row, row.actions[0])
	assert.equal(calls.length, 1)
	assert.equal(calls[0].type, "POST")
	assert.equal(calls[0].method, "custom_hr.api.leave_calendar.decide_approval")
	assert.equal(calls[0].args.modified, "STAMP")
	assert.equal(calls[0].args.action, "Approve")
	assert.equal(calls[0].args.employee, "EMP")
	resolve({})
	await pending
	assert.equal(ui.dialog.approval_busy, false)
})

test("rejected/stale decision refreshes both dialog and calendar and does not retry automatically", async () => {
	const ui = calendar()
	let posts = 0, reloads = 0
	ui.frappe.call = async () => { posts++; throw new Error("stale") }
	ui.instance.load = async () => { reloads++ }
	ui.instance.load_day = async () => { reloads++ }
	const row = item()
	await ui.instance.decide(ui.dialog, row, row.actions[0])
	assert.equal(posts, 1)
	assert.equal(reloads, 2)
	assert.equal(ui.alerts[0].indicator, "red")
})

test("requests pass the chosen kind through to the server", async () => {
	const ui = calendar()
	let args
	ui.frappe.call = async value => {
		assert.equal(value.method, "custom_hr.api.leave_calendar.get_leave_calendar")
		args = value.args
		return { message: { items: [] } }
	}
	await ui.instance.request("2026-10-01", "2026-10-31", { kind: "overtime" })
	assert.equal(args.kind, "overtime")
	await ui.instance.request("2026-10-01", "2026-10-31")
	assert.equal(args.kind, undefined)
})

test("overtime rows show as Overtime and post the decision for that one employee", async () => {
	const ui = calendar()
	const overtime = { ...item(), kind: "overtime", doctype: "Overtime Request", name: "LEMBUR-1", employee: "EMP-B", employees: [{ employee: "EMP-B", employee_name: "Crew B" }], actions: [{ action: "Setujui", kind: "approve", next_state: "Menunggu SPV" }] }
	ui.instance.request = async () => ({ items: [overtime] })
	ui.instance.load = async () => {}
	await ui.instance.load_day(ui.dialog)
	assert.equal(ui.dialog.approval_items.length, 1)
	assert.match(ui.html(), /ac-kind ac-overtime">Overtime/)
	const posts = []
	ui.frappe.call = async value => { posts.push(value); return {} }
	await ui.instance.decide(ui.dialog, overtime, overtime.actions[0])
	const decision = posts.find(post => post.method === "custom_hr.api.leave_calendar.decide_approval")
	assert.deepEqual({ ...decision.args }, { doctype: "Overtime Request", name: "LEMBUR-1", action: "Setujui", modified: "STAMP", employee: "EMP-B" })
})

test("other-stage and completed rows display read-only without decision buttons", async () => {
	const ui = calendar()
	ui.instance.request = async () => ({ items: [
		{ ...item(), status: "Menunggu PL", actions: [] },
		{ ...item(), name: "LEAVE-2", status: "Approved", calendar_status: "approved_leave", actions: [] },
	] })
	await ui.instance.load_day(ui.dialog)
	assert.equal(ui.dialog.approval_items.length, 2)
	assert.match(ui.html(), /Menunggu PL/)
	assert.match(ui.html(), /Approved/)
	assert.equal((ui.html().match(/View only/g) || []).length, 2)
	assert.ok(!ui.html().includes("ac-decision"))
	let posts = 0
	ui.frappe.call = async () => { posts++ }
	await ui.instance.decide(ui.dialog, ui.dialog.approval_items[0], item().actions[0])
	assert.equal(posts, 0)
})

test("final approval retains the same employee row and changes Leave Request to Leave", async () => {
	const ui = calendar()
	let row = { ...item(), status: "Menunggu HRD", calendar_status: "leave_request" }
	ui.instance.request = async () => ({ items: [row] })
	ui.instance.load = async () => {}
	await ui.instance.load_day(ui.dialog)
	assert.match(ui.html(), /Leave Request/)
	ui.frappe.call = async () => { row = { ...row, status: "Approved", calendar_status: "approved_leave", actions: [] } }
	await ui.instance.decide(ui.dialog, row, row.actions[0])
	assert.equal(ui.dialog.approval_items.length, 1)
	assert.equal(ui.dialog.approval_items[0].name, "LEAVE-1")
	assert.match(ui.html(), /Employee/)
	assert.match(ui.html(), /ac-approved_leave">Leave</)
	assert.ok(!ui.html().includes("Leave Request"))
	assert.ok(!ui.html().includes("ac-decision"))
})

test("original calendar layout stays simple without banners, summary cards or employee previews", () => {
	assert.ok(source.indexOf('<div class="ac-legend">') < source.indexOf('<div class="ac-scroll">'))
	for (const element of ["ac-filters", "ac-toolbar", "ac-scroll", "ac-legend"]) assert.ok(source.includes(element))
	for (const element of ["ac-overview", "ac-summary", "ac-avatar", "ac-person"]) assert.ok(!source.includes(element))
	const ui = calendar()
	ui.instance.month = dayjs("2026-10-01")
	ui.instance.render(dayjs("2026-09-27"), {})
	assert.match(ui.html(), /aria-current="date"/)
})

test("a slower day response cannot overwrite a newer refreshed table", async () => {
	const ui = calendar()
	let finishFirst
	ui.instance.request = () => new Promise(resolve => { finishFirst = resolve })
	const first = ui.instance.load_day(ui.dialog)
	ui.instance.request = async () => ({ items: [{ ...item(), status: "Approved", calendar_status: "approved_leave", actions: [] }] })
	await ui.instance.load_day(ui.dialog)
	finishFirst({ items: [item()] })
	await first
	assert.equal(ui.dialog.approval_items[0].status, "Approved")
	assert.ok(!ui.html().includes("ac-decision"))
})

test("failed calendar loading shows a retry state instead of an empty broken grid", async () => {
	const ui = calendar()
	ui.instance.month = dayjs("2026-10-01")
	ui.instance.token = 0
	ui.instance.request = async () => { throw new Error("offline") }
	await ui.instance.load()
	assert.match(ui.html(), /ac-load-error/)
	assert.match(ui.html(), /ac-retry/)
	assert.match(ui.text(), /could not be loaded/)
})

test("late previous-month responses cannot replace the current month", async () => {
	const ui = calendar()
	ui.instance.month = dayjs("2026-10-01")
	ui.instance.token = 0
	const rendered = []
	ui.instance.render = first => rendered.push(first.format("YYYY-MM-DD"))
	let finishOctober
	// the month grid reads lightweight counts straight from get_leave_counts
	ui.frappe.call = () => new Promise(resolve => { finishOctober = resolve })
	const october = ui.instance.load()
	ui.instance.month = dayjs("2026-11-01")
	ui.frappe.call = async () => ({ message: { counts: {}, total: 1 } })
	await ui.instance.load()
	finishOctober({ message: { counts: {}, total: 5 } })
	await october
	assert.deepEqual(rendered, ["2026-11-01"])
})

test("the month grid asks only for counts, never for the full request list", async () => {
	const ui = calendar()
	ui.instance.month = dayjs("2026-10-01")
	ui.instance.render = () => {}
	const calls = []
	ui.frappe.call = async args => { calls.push(args); return { message: { counts: {}, total: 0 } } }
	await ui.instance.load()
	assert.equal(calls.length, 1)
	assert.equal(calls[0].method, "custom_hr.api.leave_calendar.get_leave_counts")
	assert.equal(calls[0].args.start_date, "2026-09-27")
	assert.equal(calls[0].args.end_date, "2026-11-07")
})

const overtimeItem = (changes = {}) => ({ ...item(), kind: "overtime", doctype: "Overtime Request", name: "LEMBUR-1", details: "17:00:00 – 21:00:00 (4 hours)", start_time: "17:00:00", end_time: "21:00:00", planned_hours: 4, employee_count: 1, actions: [{ action: "Setujui", kind: "approve", next_state: "Menunggu SPV" }], ...changes })

// A stand-in for the hours cell: dataset, innerHTML and the input the editor reads.
function hoursCell(index, hours) {
	const focused = []
	return {
		dataset: { index: String(index) }, innerHTML: "", focused,
		closest() { return this },
		querySelector(selector) {
			return selector === ".ac-hours" ? { value: hours, focus: () => focused.push(selector) } : null
		},
	}
}

test("only the total hours are clickable, and only for the approver of the current stage", async () => {
	const ui = calendar()
	ui.instance.request = async () => ({ items: [overtimeItem(), overtimeItem({ name: "LEMBUR-2", actions: [] }), item()] })
	await ui.instance.load_day(ui.dialog)
	assert.equal((ui.html().match(/class="ac-time"/g) || []).length, 1)
	assert.ok(ui.html().includes('17:00 – 21:00 (<span class="ac-time-wrap" data-index="0"><button type="button" class="ac-time"'))
	assert.ok(ui.html().includes(">4</button></span> hours)"))
	assert.ok(ui.html().includes("17:00:00 – 21:00:00 (4 hours)"))  // the view-only row keeps the plain text
})

test("a click turns the total hours into a number input", () => {
	const ui = calendar()
	ui.dialog.approval_items = [overtimeItem({ employee_count: 2 })]
	const cell = hoursCell(0, "4")
	ui.instance.open_time_editor(ui.dialog, cell)
	assert.match(cell.innerHTML, /<input type="number" class="ac-hours" min="0.5" max="23.5" step="0.5" value="4"/)
	assert.ok(!cell.innerHTML.includes('type="time"'))
	assert.ok(!cell.innerHTML.includes("<button"))  // no save or cancel buttons: Enter, leaving the field, Esc
	assert.ok(cell.innerHTML.includes("apply to all {0} employees"))  // the test __ leaves placeholders unfilled
	assert.deepEqual([...cell.focused], [".ac-hours"])
})

test("saving posts the new total with the stamp and refreshes; view-only rows send nothing", async () => {
	const ui = calendar()
	ui.dialog.approval_items = [overtimeItem(), overtimeItem({ name: "LEMBUR-2", actions: [] })]
	const posts = []
	ui.frappe.call = async value => { posts.push(value); return {} }
	let reloads = 0
	ui.instance.load_day = async () => { reloads++ }
	ui.instance.load = async () => { reloads++ }
	await ui.instance.save_time(ui.dialog, hoursCell(0, "1.5"))
	assert.equal(posts[0].method, "custom_hr.api.leave_calendar.update_overtime_hours")
	assert.deepEqual({ ...posts[0].args }, { name: "LEMBUR-1", hours: 1.5, modified: "STAMP" })
	assert.equal(reloads, 2)
	await ui.instance.save_time(ui.dialog, hoursCell(1, "2"))
	for (const empty of ["", "0", "-1", "abc", "4"]) await ui.instance.save_time(ui.dialog, hoursCell(0, empty))  // "4" is unchanged
	assert.equal(posts.length, 1)
})

test("Enter then leaving the field saves once, and Esc saves nothing", async () => {
	const ui = calendar()
	ui.dialog.approval_items = [overtimeItem()]
	const posts = []
	ui.frappe.call = async value => { posts.push(value); return {} }
	ui.instance.load_day = async () => {}
	ui.instance.load = async () => {}
	const cell = hoursCell(0, "2")
	await ui.instance.save_time(ui.dialog, cell)  // Enter
	await ui.instance.save_time(ui.dialog, cell)  // the blur that follows
	assert.equal(posts.length, 1)
	const cancelled = hoursCell(0, "3")
	cancelled.dataset.done = "1"  // what Esc sets before the text is put back
	await ui.instance.save_time(ui.dialog, cancelled)
	assert.equal(posts.length, 1)
})

test("overtime stays in the day list after a decision, coloured by its status and view only", async () => {
	const ui = calendar()
	ui.instance.request = async () => ({ items: [
		overtimeItem({ name: "LEMBUR-1", status: "Waiting for Budi" }),
		overtimeItem({ name: "LEMBUR-2", status: "Disetujui", actions: [] }),
		overtimeItem({ name: "LEMBUR-3", status: "Ditolak", actions: [] }),
	] })
	await ui.instance.load_day(ui.dialog)
	assert.ok(ui.html().includes('<span class="ac-stage ac-leave_request">Waiting for Budi</span>'))
	assert.ok(ui.html().includes('<span class="ac-stage ac-approved_leave">Disetujui</span>'))
	assert.ok(ui.html().includes('<span class="ac-stage ac-rejected">Ditolak</span>'))
	assert.equal((ui.html().match(/View only/g) || []).length, 2)
	assert.equal((ui.html().match(/class="ac-time"/g) || []).length, 1)  // only the pending one has editable hours
})
