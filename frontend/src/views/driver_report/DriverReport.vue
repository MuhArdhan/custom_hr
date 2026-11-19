<template>
	<ion-page>
		<ion-content class="ion-no-padding">
			<div class="flex flex-col min-h-screen w-screen sm:w-96 bg-gray-50">
				<header class="flex flex-row bg-white shadow-sm py-4 px-3 items-center border-b sticky top-0 z-10">
					<Button variant="ghost" class="!pl-0 hover:bg-white" @click="router.back()">
						<FeatherIcon name="chevron-left" class="h-5 w-5" />
					</Button>
					<h2 class="text-xl font-semibold text-gray-900">{{ __("Position Report") }}</h2>
				</header>

				<div class="flex flex-col gap-4 p-4">
					<p v-if="loading" class="text-sm text-gray-500 text-center py-10">{{ __("Loading...") }}</p>
					<p v-else-if="loadError" class="text-sm text-red-600" role="alert">{{ loadError }}</p>

					<div v-else-if="status.submitted" class="bg-white rounded-lg p-6 shadow-sm flex flex-col items-center text-center gap-2">
						<FeatherIcon name="check-circle" class="h-10 w-10 text-green-600" />
						<h3 class="text-lg font-semibold text-gray-900">{{ __("Today's report has been sent") }}</h3>
						<p class="text-sm text-gray-600">{{ dayjs(status.submitted_at).format("HH:mm") }}</p>
					</div>

					<div v-else-if="!status.open" class="bg-white rounded-lg p-6 shadow-sm flex flex-col items-center text-center gap-3">
						<FeatherIcon name="clock" class="h-10 w-10 text-orange-600" />
						<h3 class="text-lg font-semibold text-gray-900">{{ __("Opens at {0}", [status.opens_at]) }}</h3>
						<p class="text-sm text-gray-600">{{ __("Send your photo and location once a day, from {0}.", [status.opens_at]) }}</p>
					</div>

					<div v-else class="bg-white rounded-lg p-4 shadow-sm flex flex-col gap-4">
						<img v-if="photo" :src="photo" class="w-full aspect-[3/4] max-h-[52vh] object-cover rounded-lg border border-gray-200" :alt="__('Photo')" />
						<GroomingCapture v-else @captured="photo = $event" />
						<Button v-if="photo" variant="outline" class="w-full py-5" :disabled="sending" @click="photo = null">{{ __("Retake") }}</Button>

						<div class="flex flex-col gap-2">
							<p class="text-sm" :class="hasPosition ? 'text-green-700' : 'text-gray-600'" role="status">{{ locationStatus }}</p>
							<iframe v-if="hasPosition" :src="mapUrl" class="w-full h-40 rounded-lg border border-gray-200" loading="lazy" :title="__('Location')" />
							<Button v-if="!locating" variant="ghost" class="w-full" @click="locate">{{ __("Retry location") }}</Button>
						</div>

						<p v-if="error" class="text-sm text-red-600" role="alert">{{ error }}</p>
						<Button theme="green" variant="solid" class="w-full py-5 text-base" :disabled="!photo || !hasPosition" :loading="sending" @click="send">{{ __("Submit") }}</Button>
					</div>

					<div v-if="!loading && status?.history?.length" class="flex flex-col bg-white rounded">
						<a
							v-for="item in status.history"
							:key="item.name"
							:href="item.maps_url"
							target="_blank"
							rel="noopener"
							class="flex flex-row p-3.5 items-center justify-between border-b"
						>
							<div class="flex flex-col gap-1">
								<div class="text-base text-gray-800">{{ dayjs(item.date).format("ddd, D MMM YYYY") }}</div>
								<div class="text-xs text-gray-500">{{ dayjs(item.submitted_at).format("HH:mm") }}</div>
							</div>
							<FeatherIcon name="map-pin" class="h-5 w-5 text-gray-500" />
						</a>
					</div>
				</div>
			</div>
		</ion-content>
	</ion-page>
</template>

<script setup>
import { computed, inject, onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { IonContent, IonPage } from "@ionic/vue"
import { Button, FeatherIcon, createResource, toast } from "frappe-ui"

import GroomingCapture from "@/components/GroomingCapture.vue"
import { hasCoordinates } from "@/utils/checkin"

const __ = inject("$translate")
const dayjs = inject("$dayjs")
const router = useRouter()

const status = ref(null)
const loading = ref(true)
const loadError = ref("")
const error = ref("")
const sending = ref(false)
const photo = ref(null)
const position = ref(null)
const locating = ref(false)
const locationStatus = ref("")

const statusResource = createResource({ url: "custom_hr.api.driver_report.get_driver_report_status", method: "GET", onError() {} })
const submitResource = createResource({ url: "custom_hr.api.driver_report.submit_driver_report", method: "POST", onError() {} })

const hasPosition = computed(() => hasCoordinates(position.value?.latitude, position.value?.longitude))
const mapUrl = computed(() => `https://maps.google.com/maps?q=${position.value.latitude},${position.value.longitude}&hl=en&z=15&output=embed`)

function message(err) {
	return err?.messages?.filter(Boolean).join("\n") || err?.message || __("Unable to send. Try again.")
}

function locate() {
	position.value = null
	if (!navigator.geolocation) {
		locationStatus.value = __("Geolocation is not supported by your current browser")
		return
	}
	locating.value = true
	locationStatus.value = __("Locating...")
	navigator.geolocation.getCurrentPosition(
		({ coords }) => {
			position.value = { latitude: coords.latitude, longitude: coords.longitude, accuracy: coords.accuracy }
			locationStatus.value = __("Location found (±{0} m)", [Math.round(coords.accuracy)])
			locating.value = false
		},
		() => {
			locationStatus.value = __("Unable to retrieve your location. Enable location permission and retry.")
			locating.value = false
		},
		{ enableHighAccuracy: true, timeout: 20000, maximumAge: 0 },
	)
}

async function load() {
	loading.value = true
	loadError.value = ""
	try {
		status.value = await statusResource.fetch()
		if (status.value.open && !status.value.submitted && !position.value) locate()
	} catch (err) {
		loadError.value = message(err)
	} finally {
		loading.value = false
	}
}

async function send() {
	if (!photo.value || !hasPosition.value || sending.value) return
	sending.value = true
	error.value = ""
	try {
		await submitResource.submit({ photo: photo.value, ...position.value })
		toast({ title: __("Success"), text: __("Position report sent"), icon: "check-circle", position: "bottom-center", iconClasses: "text-green-500" })
		photo.value = null
	} catch (err) {
		error.value = message(err)
	} finally {
		sending.value = false
		await load() // a refused duplicate shows today's real state
	}
}

onMounted(load)
</script>
