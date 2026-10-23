import { shallowReactive } from "vue"

// Shared by the install dialog (App root) and the Settings page. shallowReactive keeps the
// browser's BeforeInstallPromptEvent unwrapped: a Vue proxy around it breaks prompt().
export const installState = shallowReactive({ deferredPrompt: null, installed: false, iosMessage: false })

if (typeof window !== "undefined") {
	// Browsers fire this once, soon after load: listen from module load, not from a component
	// that only mounts later, or the event (and the install prompt) is lost.
	window.addEventListener("beforeinstallprompt", (event) => {
		event.preventDefault()
		installState.deferredPrompt = event
	})
	window.addEventListener("appinstalled", () => {
		installState.deferredPrompt = null
		installState.installed = true
	})
}

const currentEnv = () => ({
	userAgent: navigator.userAgent,
	standalone: !!window.matchMedia?.("(display-mode: standalone)").matches || navigator.standalone === true,
	nativeApp: !!window.Capacitor?.isNativePlatform?.(),
})

export const isIos = (env = currentEnv()) => /iphone|ipad|ipod/i.test(env.userAgent)

// Shown in any browser tab. The browser's prompt is a bonus, not a precondition: it never
// fires when the app is already installed or after the user dismissed it.
export function canInstall(state = installState, env = currentEnv()) {
	return !(env.standalone || env.nativeApp || state.installed)
}

// Returns "prompted" (browser dialog opened), "ios" (instructions shown) or "manual"
// (nothing available: the caller should tell the user to use the browser menu).
export async function requestInstall(state = installState, env = currentEnv()) {
	if (state.deferredPrompt) {
		const event = state.deferredPrompt
		// A browser accepts prompt() only once per event.
		state.deferredPrompt = null
		await event.prompt()
		return "prompted"
	}
	if (isIos(env)) {
		state.iosMessage = true
		return "ios"
	}
	return "manual"
}
