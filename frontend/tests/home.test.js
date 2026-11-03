import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs/promises"

const home = await fs.readFile(new URL("../src/views/Home.vue", import.meta.url), "utf8")

test("SOP Grooming is offered on the home screen to outlet employees only", () => {
	assert.match(home, /link\.route !== "GroomingView" \|\| employee\.data\?\.outlet/)
})
