import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { canSubmit, fitWithin, nextStep, toPayload } from "../src/utils/grooming.js"

const STEPS = ["right_hand", "left_hand", "cap", "trousers", "footwear"].map((key) => ({ key }))
const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8")

test("photos are scaled so the long side is at most the limit, never upscaled", () => {
	assert.deepEqual(fitWithin(4000, 3000, 1280), { width: 1280, height: 960 })
	assert.deepEqual(fitWithin(3000, 4000, 1280), { width: 960, height: 1280 })
	assert.deepEqual(fitWithin(800, 600, 1280), { width: 800, height: 600 })
	assert.deepEqual(fitWithin(1280, 720, 1280), { width: 1280, height: 720 })
})

test("the next step is the first one without a photo, and null when all are taken", () => {
	assert.equal(nextStep({}, STEPS), 0)
	assert.equal(nextStep({ right_hand: "a" }, STEPS), 1)
	assert.equal(nextStep({ right_hand: "a", cap: "c" }, STEPS), 1)
	assert.equal(nextStep(Object.fromEntries(STEPS.map((s) => [s.key, "x"])), STEPS), null)
})

test("submitting needs all five photos", () => {
	const photos = {}
	for (const step of STEPS) {
		assert.equal(canSubmit(photos, STEPS), false)
		photos[step.key] = "data:image/jpeg;base64,AAAA"
	}
	assert.equal(canSubmit(photos, STEPS), true)
	assert.equal(canSubmit({}, []), false)
})

test("the payload follows the step order whatever order the photos were taken in", () => {
	const photos = { footwear: "5", right_hand: "1", cap: "3", left_hand: "2", trousers: "4" }
	assert.deepEqual(toPayload(photos, STEPS), ["1", "2", "3", "4", "5"])
})

test("hiding the advance shortcut leaves its routes registered and adds the grooming one to Home", () => {
	assert.match(read("../src/router/advances.js"), /EmployeeAdvanceFormView/)
	assert.match(read("../src/router/index.js"), /employeeAdvanceRoutes/)
	const home = read("../src/views/Home.vue")
	assert.doesNotMatch(home, /EmployeeAdvanceFormView/)
	assert.match(home, /GroomingView/)
	assert.match(read("../src/router/grooming.js"), /name: "GroomingView"/)
})
