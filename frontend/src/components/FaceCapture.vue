<template>
	<div class="flex flex-col gap-3 w-full items-center">
		<div
			class="relative mx-auto h-[40vh] min-h-[220px] max-h-[460px] aspect-[3/4] max-w-full overflow-hidden rounded-lg border border-gray-200 bg-black"
		>
			<video
				v-show="cameraActive"
				ref="videoEl"
				class="absolute inset-0 w-full h-full object-cover -scale-x-100"
				autoplay
				muted
				playsinline
			/>
			<canvas
				v-show="cameraActive && faceDetected"
				ref="overlayEl"
				class="absolute inset-0 w-full h-full pointer-events-none -scale-x-100"
			/>
			<img
				v-if="lastSamplePhoto"
				:src="lastSamplePhoto"
				class="absolute inset-0 w-full h-full object-cover"
			/>
			<div
				v-if="!cameraActive && !lastSamplePhoto"
				class="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-gray-300"
			>
				{{ statusText }}
			</div>
		</div>

		<div
			class="text-sm font-medium text-center leading-snug px-1 min-h-[20px]"
			:class="statusClass"
		>
			{{ statusText }}
		</div>

		<input
			ref="fileInput"
			type="file"
			accept="image/*"
			capture="user"
			class="hidden"
			@change="handleFileSelect"
		/>

		<div class="flex flex-wrap flex-row gap-2 w-full items-center justify-center">
			<Button
				v-if="cameraActive && props.mode === 'enroll'"
				variant="solid"
				class="w-full py-4"
				:disabled="!faceDetected || capturing"
				:loading="capturing"
				@click="captureSample"
			>
				{{ captureLabel }}
			</Button>
			<Button
				v-if="cameraActive && props.mode === 'verify'"
				variant="ghost"
				class="w-full py-3 text-xs"
				:disabled="!faceDetected || capturing"
				:loading="capturing"
				@click="captureSample"
			>
				{{ __("Capture Manually") }}
			</Button>
			<Button
				v-if="fallbackNeeded"
				variant="outline"
				class="w-full py-4"
				:loading="capturing"
				@click="openFilePicker"
			>
				{{ __("Take Photo") }}
			</Button>
			<Button v-if="fallbackNeeded" variant="ghost" class="py-4" @click="retryCamera">
				{{ __("Try Camera Again") }}
			</Button>
			<Button
				v-if="lastSamplePhoto && !fallbackNeeded"
				variant="ghost"
				class="py-4"
				@click="resetCapture"
			>
				{{ __("Retake") }}
			</Button>
		</div>

		<div v-if="samplesRequired > 1" class="text-xs text-gray-500">
			{{ __("Samples: {0}/{1}", [samples.length, samplesRequired]) }}
		</div>
	</div>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from "vue"
import { Button } from "frappe-ui"
import { detectSingleFace } from "@vladmandic/face-api"

import {
	detectFace,
	detectorOptions,
	ensureLiveBackend,
	faceImage,
	loadFaceModels,
	mirroredPhoto,
	snapshotCanvas,
	withTimeout,
} from "@/utils/face"

const props = defineProps({
	mode: {
		type: String,
		default: "verify", // verify | enroll
	},
	samplesRequired: {
		type: Number,
		default: 1,
	},
})

const emit = defineEmits(["captured"])

const __ = inject("$translate")

const videoEl = ref(null)
const overlayEl = ref(null)
const fileInput = ref(null)

const cameraActive = ref(false)
const fallbackNeeded = ref(false)
const faceDetected = ref(false)
const capturing = ref(false)
const lastSamplePhoto = ref(null)
const statusText = ref("")
const statusKind = ref("info")
const samples = ref([])
const samplesPhoto = ref(null)

let cameraStream = null
let detectionTimer = null

// face must stay detected for this many detection ticks (~500ms each) before auto capture
const AUTO_CAPTURE_TICKS = 3

const statusClass = computed(() => {
	return {
		"text-gray-500": statusKind.value === "info",
		"text-green-600": statusKind.value === "success",
		"text-red-500": statusKind.value === "error",
		"text-orange-500": statusKind.value === "warn",
	}
})

const captureLabel = computed(() => {
	if (props.mode === "enroll" && props.samplesRequired > 1) {
		return __("Capture Sample {0}", [samples.value.length + 1])
	}
	return __("Verify Face")
})

// guided poses during enrollment: cover straight and both side profiles so the
// averaged face descriptor (computed on the server) is robust to head rotation
const enrollPrompts = computed(() => [
	__("Look straight at the camera"),
	__("Slowly turn your head to the LEFT"),
	__("Slowly turn your head to the RIGHT"),
	__("Look straight and lean a little closer"),
	__("Look straight again (final sample)"),
])

const currentPrompt = computed(() => {
	if (props.mode !== "enroll" || props.samplesRequired <= 1) {
		return __("Position your face in front of the camera")
	}
	const index = Math.min(samples.value.length, enrollPrompts.value.length - 1)
	return enrollPrompts.value[index]
})

function setStatus(text, kind = "info") {
	statusText.value = text
	statusKind.value = kind
}

function stopCamera() {
	if (detectionTimer) {
		clearInterval(detectionTimer)
		detectionTimer = null
	}
	if (cameraStream) {
		cameraStream.getTracks().forEach((track) => track.stop())
		cameraStream = null
	}
	if (videoEl.value) {
		videoEl.value.srcObject = null
	}
	cameraActive.value = false
	faceDetected.value = false
}

// each retry asks for less: some (older) phones refuse the size or the front-camera hint
const CAMERA_ATTEMPTS = [
	{ facingMode: "user", width: { ideal: 720 }, height: { ideal: 960 } },
	{ facingMode: "user" },
	true,
]

// the browser's real reason, in words the employee can act on
const CAMERA_ERRORS = {
	NotAllowedError: "Izin kamera ditolak. Izinkan akses kamera untuk situs ini di pengaturan browser, lalu coba lagi.",
	SecurityError: "Kamera diblokir oleh browser karena alasan keamanan.",
	NotReadableError: "Kamera sedang dipakai aplikasi lain atau bermasalah. Tutup aplikasi lain yang memakai kamera, lalu coba lagi.",
	NotFoundError: "Kamera tidak ditemukan di perangkat ini.",
	OverconstrainedError: "Kamera tidak mendukung pengaturan yang diminta.",
	AbortError: "Kamera berhenti sebelum sempat menyala.",
}

function cameraErrorText(error) {
	const name = error?.name || "Error"
	return `${__(CAMERA_ERRORS[name] || "Kamera tidak bisa dinyalakan.")} (${name}) ${__("Silakan ambil foto dengan kamera HP.")}`
}

async function startCamera(attempt = 1) {
	if (cameraActive.value) return

	try {
		cameraStream = await navigator.mediaDevices.getUserMedia({ video: CAMERA_ATTEMPTS[attempt - 1], audio: false })
		videoEl.value.srcObject = cameraStream
		await videoEl.value.play().catch(() => {})
		cameraActive.value = true
		fallbackNeeded.value = false
		setStatus(currentPrompt.value, "info")
		startDetectionLoop()
	} catch (error) {
		const errorName = error?.name || ""
		const permissionDenied = ["NotAllowedError", "SecurityError"].includes(errorName)

		if (permissionDenied || !navigator.mediaDevices?.getUserMedia) {
			fallbackNeeded.value = true
			cameraActive.value = false
			setStatus(cameraErrorText(error), "error")
			return
		}

		if (attempt < CAMERA_ATTEMPTS.length) {
			setStatus(__("Starting camera..."), "info")
			await new Promise((resolve) => setTimeout(resolve, 800))
			return startCamera(attempt + 1)
		}

		fallbackNeeded.value = true
		cameraActive.value = false
		setStatus(cameraErrorText(error), "error")
		if (fileInput.value) fileInput.value.value = ""
	}
}

function startDetectionLoop() {
	if (detectionTimer) {
		clearInterval(detectionTimer)
	}
	let steadyTicks = 0
	// a slow phone needs longer than one tick per detection: never stack them up
	let detecting = false
	detectionTimer = setInterval(async () => {
		if (detecting || !videoEl.value || !cameraActive.value || capturing.value) return
		let detection = null
		detecting = true
		try {
			await ensureLiveBackend()
			detection = await withTimeout(detectSingleFace(videoEl.value, detectorOptions()))
			faceDetected.value = Boolean(detection)
		} catch (error) {
			faceDetected.value = false
			steadyTicks = 0
			return
		} finally {
			detecting = false
		}
		try {
			drawBox(detection)
		} catch (error) {
			// never let an overlay drawing error disable the capture button
		}

		// auto verification: capture automatically once a face is held steady for ~1.5s
		if (props.mode === "verify") {
			if (detection) {
				steadyTicks += 1
				if (steadyTicks >= AUTO_CAPTURE_TICKS) {
					steadyTicks = 0
					captureSample()
				} else if (steadyTicks === 1) {
					setStatus(__("Hold still, verifying face..."), "success")
				}
			} else {
				if (steadyTicks > 0) {
					setStatus(currentPrompt.value, "info")
				}
				steadyTicks = 0
			}
		}
	}, 500)
}

function drawBox(detection) {
	const canvas = overlayEl.value
	const video = videoEl.value
	if (!canvas || !video || !video.videoWidth) return

	const displayWidth = video.clientWidth
	const displayHeight = video.clientHeight
	canvas.width = displayWidth
	canvas.height = displayHeight

	const context = canvas.getContext("2d")
	context.clearRect(0, 0, canvas.width, canvas.height)
	if (!detection) return

	// detectSingleFace() alone returns the box directly, while the landmark/descriptor
	// pipeline nests it under `.detection`; support both shapes
	const box = detection.detection?.box || detection.box
	if (!box) return
	const scaleX = displayWidth / video.videoWidth
	const scaleY = displayHeight / video.videoHeight
	context.strokeStyle = "#22c55e"
	context.lineWidth = 3
	context.strokeRect(box.x * scaleX, box.y * scaleY, box.width * scaleX, box.height * scaleY)
}

async function captureSample() {
	if (capturing.value) return
	capturing.value = true
	try {
		// snapshot the current video frame first so each sample is fresh and fast to detect
		const canvas = snapshotCanvas(videoEl.value)
		const detection = await detectFace(canvas)
		if (!detection) {
			setStatus(__("Face not detected. Please try again."), "warn")
			return
		}

		const photo = mirroredPhoto(canvas)
		samples.value.push(await faceImage(canvas, detection))
		samplesPhoto.value = samplesPhoto.value || photo
		lastSamplePhoto.value = photo

		if (samples.value.length >= props.samplesRequired) {
			stopCamera()
			emit("captured", {
				faces: samples.value,
				photo: samplesPhoto.value,
			})
		} else {
			setStatus(
				__("Sample {0}/{1} captured.", [samples.value.length, props.samplesRequired]),
				"success"
			)
			setTimeout(() => {
				lastSamplePhoto.value = null
				if (cameraActive.value) {
					setStatus(currentPrompt.value, "info")
				}
			}, 900)
		}
	} catch (error) {
		setStatus(__("Face detection failed. Please try again."), "error")
	} finally {
		capturing.value = false
	}
}

function openFilePicker() {
	fileInput.value?.click()
}

async function handleFileSelect(event) {
	const file = event.target.files?.[0]
	if (!file) return

	capturing.value = true
	try {
		const image = await loadImageFromFile(file)
		const canvas = snapshotCanvas(image)
		image.close?.()
		const detection = await detectFace(canvas)
		if (!detection) {
			setStatus(__("Face not detected in the photo. Please try again."), "warn")
			return
		}

		const photo = canvas.toDataURL("image/jpeg", 0.8)
		samples.value.push(await faceImage(canvas, detection))
		samplesPhoto.value = samplesPhoto.value || photo
		lastSamplePhoto.value = photo

		if (samples.value.length >= props.samplesRequired) {
			emit("captured", {
				faces: samples.value,
				photo: samplesPhoto.value,
			})
		} else {
			setStatus(
				__("Sample {0}/{1} captured. Take another photo.", [
					samples.value.length,
					props.samplesRequired,
				]),
				"success"
			)
		}
	} catch (error) {
		setStatus(__("Face detection failed. Please try again."), "error")
	} finally {
		capturing.value = false
		if (fileInput.value) fileInput.value.value = ""
	}
}

// A native camera photo can be 12 MP: decode it straight to the snapshot width, upright,
// instead of holding a base64 copy plus the full-size image (runs low-RAM phones out of memory).
async function loadImageFromFile(file) {
	if (typeof createImageBitmap === "function") {
		try {
			return await createImageBitmap(file, { resizeWidth: 640, imageOrientation: "from-image" })
		} catch (error) {
			// older browsers reject these options: decode the plain way below
		}
	}
	const url = URL.createObjectURL(file)
	try {
		return await new Promise((resolve, reject) => {
			const image = new Image()
			image.onload = () => resolve(image)
			image.onerror = reject
			image.src = url
		})
	} finally {
		URL.revokeObjectURL(url)
	}
}

function retryCamera() {
	fallbackNeeded.value = false
	lastSamplePhoto.value = null
	startCamera()
}

function resetCapture() {
	samples.value = []
	samplesPhoto.value = null
	lastSamplePhoto.value = null
	if (cameraActive.value) {
		setStatus(currentPrompt.value, "info")
	} else {
		fallbackNeeded.value = false
		startCamera()
	}
}

onMounted(async () => {
	setStatus(__("Loading face models..."), "info")
	try {
		await loadFaceModels()
	} catch (error) {
		setStatus(__("Failed to load face models. Please check your connection."), "error")
		return
	}

	if (!navigator.mediaDevices?.getUserMedia) {
		fallbackNeeded.value = true
		setStatus(__("Browser ini tidak mendukung kamera. Silakan ambil foto dengan kamera HP."), "error")
		return
	}

	await startCamera()
})

onBeforeUnmount(() => {
	stopCamera()
})
</script>
