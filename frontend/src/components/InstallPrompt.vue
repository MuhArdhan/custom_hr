<template>
	<!-- Install PWA dialog -->
	<Dialog v-model="showDialog">
		<template #body-title>
			<h2 class="text-lg font-bold">{{ __("Install Frappe HR") }} </h2>
		</template>
		<template #body-content>
			<p>{{ __("Get the app on your device for easy access & a better experience!") }} </p>
		</template>
		<template #actions>
			<Button variant="solid" @click="() => install()" class="py-5 w-full">
				<template #prefix><FeatherIcon name="download" class="w-4" /></template>
				{{ __("Install") }}
			</Button>
		</template>
	</Dialog>

	<!-- iOS installation info message -->
	<Popover :show="iosInstallMessage" placement="bottom">
		<template #body>
			<div
				class="mt-[calc(100vh-15rem)] flex flex-col gap-3 mx-2 rounded py-5 bg-blue-100 drop-shadow-xl"
			>
				<div
					class="flex flex-row text-center items-center justify-between mb-1 px-3"
				>
					<span class="text-base text-gray-900 font-bold">
						{{ __("Install Frappe HR") }}
					</span>
					<span class="inline-flex items-baseline">
						<FeatherIcon
							name="x"
							class="ml-auto h-4 w-4 text-gray-700"
							@click="iosInstallMessage = false"
						/>
					</span>
				</div>
				<div class="text-xs text-gray-800 px-3">
					<span class="flex flex-col gap-2">
						<span>
							{{ __("Get the app on your iPhone for easy access & a better experience") }}
						</span>
						<span class="inline-flex items-start whitespace-nowrap">
							<span>{{ __("Tap") }}&nbsp;</span>
							<FeatherIcon name="share" class="h-4 w-4 text-blue-600" />
							<span>&nbsp;{{ __('and then "Add to Home Screen"') }}</span>
						</span>
					</span>
				</div>
			</div>
		</template>
	</Popover>
</template>

<script setup>
import { ref, toRef } from "vue"

import { Dialog, Popover, FeatherIcon } from "frappe-ui"

import { installState, isIos, requestInstall } from "@/utils/installPrompt"

// The prompt event and iOS message live in shared state so Settings can reuse them.
const showDialog = ref(false)
const iosInstallMessage = toRef(installState, "iosMessage")

// Detects if device is in standalone mode
const isInStandaloneMode = () =>
	"standalone" in window.navigator && window.navigator.standalone

// Checks if should display install popup notification:
if (isIos() && !isInStandaloneMode()) {
	iosInstallMessage.value = true
}

window.addEventListener("beforeinstallprompt", (e) => {
	// Prevent the mini-infobar from appearing on mobile
	e.preventDefault()
	// The event itself is stashed in installState (utils/installPrompt) for the Settings button.
	if (isIos() && !isInStandaloneMode()) {
		iosInstallMessage.value = true
	} else {
		showDialog.value = true
	}
	// Optionally, send analytics event that PWA install promo was shown.
	console.log(`'beforeinstallprompt' event was fired.`)
})

window.addEventListener("appinstalled", () => {
	showDialog.value = false
})

async function install() {
	showDialog.value = false
	await requestInstall()
}
</script>
