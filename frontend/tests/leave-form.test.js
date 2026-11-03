import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs/promises"

const source = await fs.readFile(new URL("../src/views/leave/Form.vue", import.meta.url), "utf8")

test("the leave form hides the approver choice: the server routes outlet and department leave by stage", () => {
	// a picked approver was overwritten at the first stage anyway (leave_approver.hand_over_to_approver_2)
	assert.match(source, /\["leave_approver", "leave_approver_name"\]\.includes\(field\.fieldname\)\) field\.hidden = true/)
})

test("a new leave form also drops the then-empty Approval section heading", () => {
	assert.match(source, /field\.fieldname === "section_break_7" && !props\.id\) field\.hidden = true/)
})

const formView = await fs.readFile(new URL("../src/components/FormView.vue", import.meta.url), "utf8")

test("the form header names who the leave waits for, coloured by its real stage", () => {
	assert.match(formView, /leaveDetailStatus\(formModel\.value, stateField\)/)
	assert.match(formView, /guessStatusColor\(props\.doctype, workflowState\.value\)/)
})

test("loading a saved leave never blanks its stored approver name", () => {
	// the approver options can arrive after the document; an unknown approver keeps the name the server stored
	assert.match(source, /if \(selected\) leaveApplication\.value\.leave_approver_name = selected\.full_name/)
	assert.doesNotMatch(source, /leave_approver_name = selected\?\.full_name \|\| ""/)
})

const workflow = await fs.readFile(new URL("../src/composables/workflow.js", import.meta.url), "utf8")

test("the app's workflow action sheet lists each action once, like the Working Calendar", () => {
	assert.match(workflow, /\.map\(\(transition\) => transition\.action\)[^]{0,160}?\.filter\(\(action, index, actions\) => actions\.indexOf\(action\) === index\)/)
})
