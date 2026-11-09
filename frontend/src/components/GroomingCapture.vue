<template>
	<div class="flex flex-col gap-3 w-full">
		<div class="relative w-full aspect-[3/4] max-h-[52vh] overflow-hidden rounded-lg bg-black">
			<video v-show="cameraActive" ref="videoEl" class="absolute inset-0 w-full h-full object-cover" :class="{ '-scale-x-100': facing === 'user' }" autoplay muted playsinline />
			<div v-if="!cameraActive" class="absolute inset-0 flex flex-col items-center justify-center gap-2 px-6 text-center text-sm text-gray-300">
				<FeatherIcon name="camera" class="h-8 w-8 text-gray-500" />
				{{ statusText }}
			</div>
			<button
				v-if="cameraActive"
				type="button"
				class="absolute top-3 right-3 h-9 w-9 flex items-center justify-center rounded-full bg-black/40 text-white"
				:aria-label="__('Switch Camera')"
				@click="switchCamera"
			>
				<FeatherIcon name="refresh-cw" class="h-4 w-4" />
			</button>
		</div>
		<Button v-if="cameraActive" theme="green" variant="solid" class="w-full py-5 text-base" @click="capture">
			<template #prefix><FeatherIcon name="camera" class="w-4" /></template>
			{{ __("Take Photo") }}
		</Button>
		<template v-if="fallbackNeeded">
			<Button theme="green" variant="solid" class="w-full py-5 text-base" @click="fileInput.click()">
				<template #prefix><FeatherIcon name="camera" class="w-4" /></template>
				{{ __("Take Photo") }}
			</Button>
			<Button variant="ghost" class="w-full" @click="startCamera">{{ __("Try Camera Again") }}</Button>
		</template>
		<input ref="fileInput" type="file" accept="image/*" capture="user" class="hidden" @change="handleFile" />
	</div>
</template>

<script setup>
import { inject, onBeforeUnmount, onMounted, ref } from "vue"
import { Button, FeatherIcon } from "frappe-ui"

import { fitWithin } from "@/utils/grooming"

const emit = defineEmits(["captured"])
const __ = inject("$translate")

const MAX_SIDE = 1280
const QUALITY = 0.8

const videoEl = ref(null)
const fileInput = ref(null)
const cameraActive = ref(false)
const fallbackNeeded = ref(false)
const statusText = ref("")
let stream = null
const facing = ref("user")

function stopCamera() {
	stream?.getTracks().forEach((track) => track.stop())
	stream = null
	cameraActive.value = false
}

async function startCamera() {
	stopCamera()
	fallbackNeeded.value = false
	statusText.value = __("Starting camera...")
	// An unanswered permission prompt never rejects: offer the device camera after a few seconds.
	const timer = setTimeout(() => { if (!cameraActive.value) fallbackNeeded.value = true }, 6000)
	try {
		stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: facing.value, width: { ideal: 1280 } }, audio: false })
		videoEl.value.srcObject = stream
		cameraActive.value = true
		fallbackNeeded.value = false
	} catch {
		statusText.value = __("Unable to access the camera")
		fallbackNeeded.value = true
	} finally {
		clearTimeout(timer)
	}
}

function switchCamera() {
	facing.value = facing.value === "environment" ? "user" : "environment"
	startCamera()
}

function toDataUrl(source, width, height, mirror = false) {
	const size = fitWithin(width, height, MAX_SIDE)
	const canvas = document.createElement("canvas")
	canvas.width = size.width
	canvas.height = size.height
	const context = canvas.getContext("2d")
	if (mirror) {
		context.translate(size.width, 0)
		context.scale(-1, 1)
	}
	context.drawImage(source, 0, 0, size.width, size.height)
	return canvas.toDataURL("image/jpeg", QUALITY)
}

function capture() {
	const video = videoEl.value
	if (!video?.videoWidth) return
	emit("captured", toDataUrl(video, video.videoWidth, video.videoHeight, facing.value === "user"))
}

function handleFile(event) {
	const file = event.target.files?.[0]
	event.target.value = ""
	if (!file) return
	const image = new Image()
	image.onload = () => {
		emit("captured", toDataUrl(image, image.naturalWidth, image.naturalHeight))
		URL.revokeObjectURL(image.src)
	}
	image.src = URL.createObjectURL(file)
}

onMounted(startCamera)
onBeforeUnmount(stopCamera)
</script>
