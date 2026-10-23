import test from "node:test"
import assert from "node:assert/strict"

import { canInstall, installState, requestInstall } from "../src/utils/installPrompt.js"

const ANDROID = "Mozilla/5.0 (Linux; Android 14) Chrome/130 Mobile"
const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1"
const env = (changes = {}) => ({ userAgent: ANDROID, standalone: false, nativeApp: false, ...changes })
const fresh = (changes = {}) => ({ deferredPrompt: null, installed: false, iosMessage: false, ...changes })
const promptEvent = () => ({ calls: 0, prompt() { this.calls++; return Promise.resolve() } })

test("install button is shown in a normal browser tab, with or without a browser install prompt", () => {
	assert.equal(canInstall(fresh({ deferredPrompt: promptEvent() }), env()), true)
	// Browsers fire beforeinstallprompt once, and not at all when already installed or
	// dismissed: the button must not depend on it.
	assert.equal(canInstall(fresh(), env()), true)
	assert.equal(canInstall(fresh(), env({ userAgent: IPHONE })), true)
})

test("install button is hidden once the app runs standalone, is installed, or is the Android wrapper", () => {
	const deferredPrompt = promptEvent()
	assert.equal(canInstall(fresh({ deferredPrompt }), env({ standalone: true })), false)
	assert.equal(canInstall(fresh({ deferredPrompt }), env({ nativeApp: true })), false)
	assert.equal(canInstall(fresh({ deferredPrompt, installed: true }), env()), false)
	assert.equal(canInstall(fresh(), env({ userAgent: IPHONE, standalone: true })), false)
})

test("requestInstall prompts once and drops the event, which browsers allow only a single time", async () => {
	const event = promptEvent()
	const state = fresh({ deferredPrompt: event })
	assert.equal(await requestInstall(state, env()), "prompted")
	assert.equal(event.calls, 1)
	assert.equal(state.deferredPrompt, null)
	assert.equal(await requestInstall(state, env()), "manual")
	assert.equal(event.calls, 1)
})

test("requestInstall on iOS opens the Add to Home Screen steps instead of prompting", async () => {
	const state = fresh()
	assert.equal(await requestInstall(state, env({ userAgent: IPHONE })), "ios")
	assert.equal(state.iosMessage, true)
})

test("requestInstall without a browser prompt asks the caller to show manual instructions", async () => {
	const state = fresh()
	assert.equal(await requestInstall(state, env()), "manual")
	assert.deepEqual({ ...state }, fresh())
})

test("the shared state keeps the browser's event unwrapped so prompt() still works", () => {
	const event = promptEvent()
	installState.deferredPrompt = event
	assert.equal(installState.deferredPrompt, event)
	installState.deferredPrompt = null
})
