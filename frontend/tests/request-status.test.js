import test from "node:test"
import assert from "node:assert/strict"
import { isWaiting, leaveDetailStatus, listStatus, waitingLabel } from "../src/utils/requestStatus.js"

test("every pending stage reads Menunggu in lists; other states stay as they are", () => {
	for (const state of ["Menunggu PL", "Menunggu HRD", "Menunggu Leader", "Menunggu SPV"]) assert.equal(listStatus(state), "Menunggu")
	for (const state of ["Open", "Approved", "Rejected", "Disetujui", "Ditolak", undefined]) assert.equal(listStatus(state), state)
	assert.equal(isWaiting(null), false)
})

test("the detail names who a pending request waits for", () => {
	assert.equal(waitingLabel("Menunggu Leader", "Budi"), "Menunggu Budi")
	assert.equal(waitingLabel("Menunggu HRD", "HRD"), "Menunggu HRD")
	assert.equal(waitingLabel("Menunggu SPV", null), "Menunggu SPV")
	assert.equal(waitingLabel("Disetujui", "Budi"), "Disetujui")
})

test("leave at the PL stage shows the leave approver; HRD and final states are left alone", () => {
	const doc = { leave_workflow_state: "Menunggu PL", leave_approver: "pl@example.com", leave_approver_name: "Siti" }
	assert.equal(leaveDetailStatus(doc, "leave_workflow_state"), "Menunggu Siti")
	assert.equal(leaveDetailStatus({ ...doc, leave_approver_name: "" }, "leave_workflow_state"), "Menunggu pl@example.com")
	assert.equal(leaveDetailStatus({ ...doc, leave_workflow_state: "Menunggu HRD" }, "leave_workflow_state"), "Menunggu HRD")
	assert.equal(leaveDetailStatus({ ...doc, leave_workflow_state: "Approved" }, "leave_workflow_state"), null)
	assert.equal(leaveDetailStatus(doc, undefined), null)
	assert.equal(leaveDetailStatus(null, "leave_workflow_state"), null)
})
