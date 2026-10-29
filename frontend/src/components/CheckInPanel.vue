<template>
	<div class="flex flex-col bg-white rounded w-full py-6 px-4 border-none">
		<h2 class="text-lg font-bold text-gray-900">{{ __("Hey, {0} 👋", [employee?.data?.first_name]) }}</h2>
		<template v-if="settings.data?.allow_employee_checkin_from_mobile_app && sameEmployee">
			<div class="font-medium text-sm text-gray-500 mt-1.5">
				<template v-if="lastLog">
					<span>{{ __("Last {0} was at {1}", [__(lastLog.log_type === 'IN' ? 'check-in' : 'check-out'), formatSiteDateTime(lastLog.time)]) }}</span>
					<span class="whitespace-pre"> &middot; </span>
				</template>
				<router-link :to="{ name: 'EmployeeCheckinListView' }" class="underline">{{ __("View List") }}</router-link>
			</div>
			<div v-if="context" class="mt-3 text-sm text-gray-700 space-y-1" aria-live="polite">
				<div v-if="context.outlet">{{ context.outlet }}</div>
				<div v-if="displayShift">{{ shiftLabel(displayShift) }}</div>
			</div>
			<div v-if="choices.length" class="mt-3">
				<label for="shift-choice" class="block text-xs text-gray-600 mb-1">{{ __("Choose your shift") }}</label>
				<select id="shift-choice" v-model="chosenShift" class="w-full rounded border border-gray-300 px-2 py-2 text-sm" :disabled="submission.busy">
					<option value="" disabled>{{ __("Select shift") }}</option>
					<option v-for="choice in choices" :key="choice.shift" :value="choice.shift">{{ shiftChoiceLabel(choice) }}</option>
				</select>
			</div>
			<p v-if="submission.pending?.uncertain && !submission.busy" class="mt-3 text-sm text-orange-700" role="status">
				{{ __("The previous request is not confirmed. Check its status or retry the same action; do not start a new session.") }}
				<span v-if="submission.pending.work_date" class="block">{{ __("Original attempt work date") }}: {{ submission.pending.work_date }}</span>
			</p>
			<p v-if="contextError || (!context?.allowed && context?.message && !(context.next_action === 'DONE' && context.reason === 'session_complete_or_expired'))" class="mt-3 text-sm text-orange-700" role="status">{{ contextError || context.message }}</p>
			<p v-if="submitError" class="mt-2 text-sm text-red-600" role="alert">{{ submitError }}</p>
			<Button class="mt-4 mb-1 py-5 text-base" :theme="action === 'OUT' ? 'red' : 'green'" variant="solid" :loading="opening || submission.busy" :disabled="!canOpen" @click="openCheckin">
				<template #prefix><FeatherIcon :name="action === 'OUT' ? 'arrow-left-circle' : 'arrow-right-circle'" class="w-4" /></template>
				{{ actionLabel }}
			</Button>
		</template>
	</div>

	<ion-modal :is-open="modalOpen && sameEmployee && settings.data?.allow_employee_checkin_from_mobile_app" :initial-breakpoint="1" :breakpoints="[0, 1]" :can-dismiss="!submission.busy || !sameEmployee" @didDismiss="closeModal">
		<div v-if="modalOpen && sameEmployee && settings.data?.allow_employee_checkin_from_mobile_app" class="w-full min-h-full flex flex-col items-center gap-4 px-4 pt-6 pb-10 overflow-y-auto">
			<h3 class="font-bold text-xl">{{ actionLabel }}</h3>
			<template v-if="settings.data?.allow_geolocation_tracking">
				<p class="text-sm text-center" :class="locationValid ? 'text-green-700' : 'text-orange-700'" role="status" aria-live="polite">{{ locationStatus }}</p>
				<iframe v-if="gpsAvailable" class="w-full rounded border" height="170" :src="mapUrl" :title="__('Current location')" />
				<Button :disabled="locationChecking || submission.busy" variant="ghost" @click="fetchLocation">{{ __("Retry location") }}</Button>
			</template>
			<p v-if="verifyError" class="text-sm text-red-600 text-center" role="alert">{{ verifyError }}</p>
			<template v-if="useFace">
				<p v-if="!faceStatusChecked" class="text-sm text-gray-600">{{ __("Checking face enrollment...") }}</p>
				<template v-else-if="faceStep === 'enroll'">
					<p class="text-sm text-gray-600">{{ __("Enroll your face to start using face attendance.") }}</p>
					<FaceCapture mode="enroll" :samples-required="settings.data?.face_enroll_samples || 3" @captured="handleEnrolled" />
				</template>
				<FaceCapture v-else-if="faceStep === 'capture'" mode="verify" @captured="handleFaceCaptured" />
				<template v-else>
					<img v-if="capturedPhoto" :src="capturedPhoto" class="w-40 h-40 object-contain bg-black rounded-lg" :alt="__('Captured face')" />
					<p v-if="submission.busy" class="text-sm text-gray-600" role="status">{{ __("Submitting...") }}</p>
					<Button v-if="showRetry" variant="solid" class="w-full py-5" @click="submitAttempt">{{ __("Try Again") }}</Button>
					<Button :disabled="submission.busy" variant="ghost" class="w-full" @click="retakeFace">{{ __("Retake Face") }}</Button>
				</template>
			</template>
			<template v-else>
				<p v-if="submission.busy" class="text-sm text-gray-600" role="status">{{ __("Submitting...") }}</p>
				<Button v-if="showRetry" variant="solid" class="w-full py-5" @click="submitAttempt">{{ __("Try Again") }}</Button>
			</template>
			<Button :disabled="submission.busy" variant="ghost" @click="closeModal">{{ __("Close") }}</Button>
		</div>
	</ion-modal>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import { createListResource, createResource, FeatherIcon, toast } from "frappe-ui"
import { IonModal } from "@ionic/vue"
import FaceCapture from "@/components/FaceCapture.vue"
import { settings } from "@/data/settings"
import { shiftLabel } from "@/data/shiftTimes"
import { CheckinSubmission, formatSiteDateTime, hasCoordinates, shiftChoiceLabel, shiftChoices, validContext } from "@/utils/checkin"
import { requireAndroidAttendanceDevice } from "@/utils/androidDevice"

const employee = inject("$employee")
const socket = inject("$socket")
const __ = inject("$translate")
const employeeName = employee.data.name
let storage
try { storage = window.sessionStorage } catch { storage = null }
const submission = reactive(new CheckinSubmission(employeeName, storage, window.crypto))
const context = ref(null)
const contextError = ref("")
const syncing = ref(false)
const opening = ref(false)
const modalOpen = ref(false)
const latitude = ref(null)
const longitude = ref(null)
const locationStatus = ref("")
const locationValid = ref(false)
const locationChecking = ref(false)
const faceStep = ref("capture")
const faceStatusChecked = ref(false)
const capturedDescriptor = ref(null)
const capturedPhoto = ref(null)
const verifyError = ref("")
const submitError = ref("")
const online = ref(navigator.onLine !== false)
let disposed = false
let locationGeneration = 0
let refreshTimer
let confirming = false
// One automatic submit per verified attempt: a failure must wait for "Try Again", a new GPS
// check or a new face capture instead of looping.
let attempted = false

const requestContext = createResource({ url: "custom_hr.api.checkin.get_checkin_context", method: "GET", onError() {} })
const locationCheck = createResource({ url: "custom_hr.api.checkin.validate_checkin_location", method: "POST", onError() {} })
const requestResult = createResource({ url: "custom_hr.api.checkin.get_checkin_request_result", method: "GET", onError() {} })
const standardCheckin = createResource({ url: "custom_hr.api.checkin.submit_checkin", method: "POST", onError() {} })
const faceCheckin = createResource({ url: "custom_hr.api.face.face_checkin", method: "POST", onError() {} })
const faceStatus = createResource({ url: "custom_hr.api.face.get_face_status", method: "GET", onError() {} })
const enrollFace = createResource({ url: "custom_hr.api.face.enroll_face", method: "POST", onError() {} })
const checkins = createListResource({
	doctype: "Employee Checkin",
	fields: ["name", "log_type", "time", "shift", "outlet_at_checkin", "shift_work_date", "checkout_deadline", "paired_checkin", "attendance_source", "face_verified"],
	filters: { employee: employeeName }, orderBy: "time desc",
})
const lastLog = computed(() => checkins.data?.[0] || null)
const displayShift = computed(() => context.value?.candidate_shift || (context.value?.next_action === "DONE" ? submission.lastResult?.shift || lastLog.value?.shift : null))
const action = computed(() => submission.pending?.log_type || context.value?.next_action)
const chosenShift = ref("")
const choices = computed(() => shiftChoices(context.value, action.value))
const choiceMade = computed(() => !choices.value.length || !!chosenShift.value)
watch(choices, (list) => { if (!list.some((choice) => choice.shift === chosenShift.value)) chosenShift.value = "" })
const actionLabel = computed(() => submission.pending?.uncertain && !submission.busy ? __("Retry {0}", [submission.pending.log_type]) : action.value === "OUT" ? __("Check Out") : action.value === "DONE" ? __("Attendance Completed") : __("Check In"))
const useFace = computed(() => submission.pending?.channel === "face" || settings.data?.enable_face_checkin || settings.data?.require_face_checkin)
const gpsAvailable = computed(() => hasCoordinates(latitude.value, longitude.value))
const mapUrl = computed(() => `https://maps.google.com/maps?q=${latitude.value},${longitude.value}&hl=en&z=15&output=embed`)
const sameEmployee = computed(() => employee.data?.name === employeeName)
const canOpen = computed(() => sameEmployee.value && online.value && !syncing.value && !opening.value && !submission.busy && choiceMade.value && (submission.pending?.uncertain || (context.value?.allowed && ["IN", "OUT"].includes(context.value.next_action))))
const canSubmit = computed(() => settings.data?.allow_employee_checkin_from_mobile_app && sameEmployee.value && online.value && !syncing.value && !!submission.pending && choiceMade.value && (submission.pending.uncertain || (context.value?.allowed && context.value.next_action === submission.pending.log_type)) && (!settings.data?.allow_geolocation_tracking || (gpsAvailable.value && locationValid.value && !locationChecking.value)) && (!useFace.value || !!capturedDescriptor.value))

const showRetry = computed(() => !submission.busy && !!(verifyError.value || submitError.value) && canSubmit.value)

watch(() => modalOpen.value && canSubmit.value, (ready) => {
	if (!ready || attempted) return
	attempted = true
	submitAttempt()
})

function message(error) {
	return error?.messages?.filter(Boolean).join("\n") || error?.message || __("Unable to confirm attendance. Refresh the status and retry.")
}

function saved(result) {
	submitError.value = ""
	toast({ title: __("Success"), text: __("{0} saved. Shift: {1}", [result.log_type, shiftLabel(result.shift) || "—"]), icon: "check-circle", position: "bottom-center", iconClasses: "text-green-500" })
	closeModal()
}

async function syncState() {
	if (disposed || !sameEmployee.value || syncing.value || submission.busy) return false
	syncing.value = true
	try {
		const recovered = await submission.recover((request_id) => requestResult.fetch({ request_id }))
		if (disposed || !sameEmployee.value) return false
		if (recovered) saved(recovered)
		const [, data] = await Promise.all([settings.reload(), requestContext.fetch()])
		if (disposed || !sameEmployee.value) return false
		if (!validContext(data, employeeName)) throw new Error(__("Invalid check-in context. Refresh the page."))
		context.value = data
		contextError.value = ""
		await checkins.reload()
		return true
	} catch (error) {
		if (!disposed) {
			context.value = null // Never keep an old action enabled after a failed refresh.
			contextError.value = message(error)
		}
		return false
	} finally {
		syncing.value = false
	}
}

async function openCheckin() {
	if (!canOpen.value) return
	opening.value = true
	try {
		await requireAndroidAttendanceDevice()
		if (disposed || !sameEmployee.value) return
		const wasUncertain = !!submission.pending?.uncertain
		if (!(await syncState()) && !submission.pending?.uncertain) return
		if (!sameEmployee.value || disposed || (wasUncertain && !submission.pending)) return
		if (!submission.pending?.uncertain && !context.value?.allowed) return
		submission.begin(context.value?.next_action, useFace.value ? "face" : "standard", { checkin: context.value?.paired_checkin, workDate: context.value?.shift_work_date })
		submitError.value = ""
		verifyError.value = ""
		retakeFace()
		attempted = false
		modalOpen.value = true
		latitude.value = longitude.value = null
		// Do not request GPS permission when the server setting is disabled.
		if (settings.data?.allow_geolocation_tracking) fetchLocation()
		faceStatusChecked.value = !useFace.value
		if (useFace.value) {
			try {
				const status = await faceStatus.fetch()
				if (modalOpen.value && !disposed) faceStep.value = status?.enrolled ? "capture" : "enroll"
			} catch (error) { verifyError.value = message(error) }
			finally { faceStatusChecked.value = true }
		}
	} catch (error) { contextError.value = message(error) }
	finally { opening.value = false }
}

function fetchLocation() {
	if (submission.busy || !modalOpen.value || !sameEmployee.value) return
	attempted = false
	const generation = ++locationGeneration
	latitude.value = longitude.value = null
	locationValid.value = false
	locationChecking.value = false
	if (!navigator.geolocation) {
		locationStatus.value = __("Geolocation is not supported by your current browser")
		return
	}
	locationStatus.value = __("Locating...")
	navigator.geolocation.getCurrentPosition(async (position) => {
		if (disposed || !sameEmployee.value || !modalOpen.value || generation !== locationGeneration) return
		latitude.value = position.coords.latitude
		longitude.value = position.coords.longitude
		locationStatus.value = __("Checking location...")
		locationChecking.value = true
		try {
			const result = await locationCheck.submit({ latitude: latitude.value, longitude: longitude.value, log_type: submission.pending?.log_type, expected_checkin: submission.pending?.expected_checkin })
			if (disposed || !sameEmployee.value || !modalOpen.value || generation !== locationGeneration) return
			locationValid.value = result?.valid === true
			locationStatus.value = locationValid.value ? __("Location verified") : __("Unable to verify location. Please retry.")
		} catch (error) {
			if (!disposed && sameEmployee.value && modalOpen.value && generation === locationGeneration) locationStatus.value = message(error)
		} finally {
			if (generation === locationGeneration) locationChecking.value = false
		}
	}, () => {
		if (!disposed && modalOpen.value && generation === locationGeneration) locationStatus.value = __("Unable to retrieve your location. Enable location permission and retry.")
	}, { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 })
}

function retakeFace() {
	if (submission.busy) return
	attempted = false
	faceStep.value = "capture"
	capturedDescriptor.value = capturedPhoto.value = null
	verifyError.value = ""
}

function handleFaceCaptured({ descriptors, photo }) {
	if (!modalOpen.value || !sameEmployee.value || submission.busy) return
	capturedDescriptor.value = descriptors?.[0] || null
	capturedPhoto.value = photo
	faceStep.value = "confirm"
	verifyError.value = ""
}

async function handleEnrolled({ descriptors, photo }) {
	if (enrollFace.loading || submission.busy || !modalOpen.value || !sameEmployee.value) return
	try {
		await enrollFace.submit({ employee: employeeName, descriptors: JSON.stringify(descriptors), photo })
		if (modalOpen.value && !disposed) retakeFace()
	} catch (error) { verifyError.value = message(error) }
	finally { enrollFace.reset() }
}

async function submitAttempt() {
	if (!canSubmit.value || submission.busy || !modalOpen.value || confirming) return
	confirming = true
	verifyError.value = ""
	let rejectedLocation = false
	try {
		await requireAndroidAttendanceDevice()
		// Native checks are asynchronous: the modal/account may have changed.
		if (disposed || !sameEmployee.value || !modalOpen.value || !canSubmit.value) return
		const payload = { latitude: latitude.value, longitude: longitude.value }
		if (choices.value.length) payload.shift = chosenShift.value
		if (useFace.value) {
			payload.descriptor = JSON.stringify(capturedDescriptor.value)
			payload.photo = capturedPhoto.value
		}
		const result = await submission.submit((params) => (useFace.value ? faceCheckin : standardCheckin).submit(params), payload)
		if (!disposed && result) saved(result)
	} catch (error) {
		rejectedLocation = error?.exc_type === "CheckinRadiusExceededError"
		if (rejectedLocation) {
			// Keep the native server message verbatim inside the location section.
			locationValid.value = false
			locationStatus.value = message(error)
			submitError.value = ""
		} else {
			verifyError.value = message(error)
			submitError.value = message(error)
			if (!submission.pending) closeModal()
		}
	} finally {
		confirming = false
		faceCheckin.reset()
		standardCheckin.reset()
		if (!disposed) await syncState()
		if (rejectedLocation && !disposed && sameEmployee.value && modalOpen.value && !submission.pending && context.value?.allowed) {
			// A definitive rejection cleared the UUID. Prepare an unsent retry;
			// another GPS check and explicit confirmation are still required.
			submission.begin(context.value.next_action, useFace.value ? "face" : "standard", { checkin: context.value.paired_checkin, workDate: context.value.shift_work_date })
		}
	}
}

function closeModal() {
	if (submission.busy) return
	attempted = false
	modalOpen.value = false
	locationGeneration++
	locationValid.value = false
	locationChecking.value = false
	latitude.value = longitude.value = null
	retakeFace()
	faceCheckin.reset()
	standardCheckin.reset()
	if (!enrollFace.loading) enrollFace.reset()
	submission.cancelUnsent()
}

function onListUpdate(data) { if (data.doctype === "Employee Checkin") syncState() }
function onOnline() { online.value = true; syncState() }
function onOffline() { online.value = false }
function onVisible() { if (document.visibilityState === "visible") syncState() }

onMounted(() => {
	socket?.emit("doctype_subscribe", "Employee Checkin")
	socket?.on("list_update", onListUpdate)
	socket?.on("connect", onOnline)
	window.addEventListener("online", onOnline)
	window.addEventListener("offline", onOffline)
	window.addEventListener("focus", onVisible)
	document.addEventListener("visibilitychange", onVisible)
	refreshTimer = window.setInterval(onVisible, 30000)
	syncState()
})

onBeforeUnmount(() => {
	disposed = true
	locationGeneration++
	socket?.emit("doctype_unsubscribe", "Employee Checkin")
	socket?.off("list_update", onListUpdate)
	socket?.off("connect", onOnline)
	window.removeEventListener("online", onOnline)
	window.removeEventListener("offline", onOffline)
	window.removeEventListener("focus", onVisible)
	document.removeEventListener("visibilitychange", onVisible)
	window.clearInterval(refreshTimer)
	capturedDescriptor.value = capturedPhoto.value = null
	submission.cancelUnsent()
})
</script>
