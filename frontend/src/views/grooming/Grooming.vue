<template>
	<ion-page>
		<ion-content class="ion-no-padding">
			<div class="flex flex-col min-h-screen w-screen sm:w-96 bg-gray-50">
				<header class="flex flex-row bg-white shadow-sm py-4 px-3 items-center border-b sticky top-0 z-10">
					<Button variant="ghost" class="!pl-0 hover:bg-white" @click="goBack">
						<FeatherIcon name="chevron-left" class="h-5 w-5" />
					</Button>
					<h2 class="text-xl font-semibold text-gray-900">{{ __("Grooming") }}</h2>
				</header>

				<div class="flex flex-col gap-4 p-4">
					<p v-if="loading" class="text-sm text-gray-500 text-center py-10">{{ __("Loading...") }}</p>
					<p v-else-if="loadError" class="text-sm text-red-600" role="alert">{{ loadError }}</p>

					<!-- Before checking in -->
					<div v-else-if="view === 'needs_checkin'" class="bg-white rounded-lg p-6 shadow-sm flex flex-col items-center text-center gap-3">
						<div class="h-14 w-14 rounded-full bg-orange-50 flex items-center justify-center">
							<FeatherIcon name="clock" class="h-7 w-7 text-orange-600" />
						</div>
						<h3 class="text-lg font-semibold text-gray-900">{{ __("Check in first") }}</h3>
						<p class="text-sm text-gray-600">{{ __("Grooming opens after you check in today.") }}</p>
						<Button variant="solid" class="w-full py-5" @click="goBack">{{ __("Go to Home") }}</Button>
					</div>

					<!-- Review all five photos, then send -->
					<div v-else-if="view === 'capture' && reviewing" class="bg-white rounded-lg p-4 shadow-sm flex flex-col gap-4">
						<div>
							<h3 class="text-lg font-semibold text-gray-900">{{ __("Check your photos") }}</h3>
							<p class="text-sm text-gray-500 mt-1">{{ __("Tap a photo to retake it.") }}</p>
						</div>
						<div class="grid grid-cols-3 gap-2">
							<button v-for="(item, position) in steps" :key="item.key" type="button" class="flex flex-col gap-1 text-left" @click="retake(position)">
								<img :src="photos[item.key]" :alt="item.title" class="w-full aspect-[3/4] object-cover rounded-lg border border-gray-200" />
								<span class="text-xs text-gray-600 leading-tight">{{ position + 1 }}. {{ item.title }}</span>
							</button>
						</div>
						<p v-if="error" class="text-sm text-red-600" role="alert">{{ error }}</p>
						<Button theme="green" variant="solid" class="w-full py-5 text-base" :loading="sending" @click="send">{{ __("Submit") }}</Button>
						<Button variant="ghost" class="w-full" :disabled="sending" @click="reviewing = false">{{ __("Back") }}</Button>
					</div>

					<!-- One step at a time -->
					<div v-else-if="view === 'capture' && step" class="bg-white rounded-lg p-4 shadow-sm flex flex-col gap-4">
						<div class="flex flex-row gap-1" role="progressbar" :aria-valuenow="index + 1" :aria-valuemax="steps.length">
							<div v-for="(item, position) in steps" :key="item.key" class="h-1.5 flex-1 rounded-full" :class="position === index ? 'bg-gray-800' : photos[item.key] ? 'bg-green-500' : 'bg-gray-200'" />
						</div>
						<p v-if="status.shift" class="text-xs text-gray-500">{{ __("Shift") }}: {{ shiftLabel(status.shift) }}</p>
						<div>
							<p class="text-xs font-medium text-gray-500 uppercase tracking-wide">{{ __("Step {0} of {1}", [index + 1, steps.length]) }}</p>
							<h3 class="text-xl font-semibold text-gray-900 mt-1">{{ step.title }}</h3>
							<p class="text-sm text-gray-600 mt-1">{{ step.hint }}</p>
						</div>

						<img v-if="photos[step.key]" :src="photos[step.key]" class="w-full aspect-[3/4] max-h-[52vh] object-cover rounded-lg border border-gray-200" :alt="step.title" />
						<GroomingCapture v-else :key="step.key" @captured="photos[step.key] = $event" />

						<template v-if="photos[step.key]">
							<div class="flex flex-row gap-2">
								<Button variant="outline" class="flex-1 py-5" @click="photos[step.key] = null">{{ __("Retake") }}</Button>
								<Button v-if="index < steps.length - 1" theme="green" variant="solid" class="flex-1 py-5" @click="index++">{{ __("Next") }}</Button>
								<Button v-else-if="ready" theme="green" variant="solid" class="flex-1 py-5" @click="reviewing = true">{{ __("Review") }}</Button>
							</div>
						</template>
						<Button v-if="index > 0" variant="ghost" class="w-full" @click="index--">{{ __("Back") }}</Button>
					</div>

					<!-- History, laid out like the attendance (Employee Checkin) history -->
					<div v-if="view === 'history' || (view === 'needs_checkin' && history.length)" class="flex flex-col w-full">
						<p v-if="view === 'history'" class="text-sm text-gray-600 text-center">{{ __("Today's grooming has been sent") }}</p>
						<div class="flex flex-col bg-white rounded mt-5">
							<router-link
								v-for="item in history"
								:key="item.name"
								:to="{ name: 'GroomingDetailView', params: { id: item.name } }"
								class="flex flex-row p-3.5 items-center justify-between border-b cursor-pointer"
							>
								<div class="flex flex-row items-center gap-3 grow min-w-0">
									<FeatherIcon :name="reviewStyle(item.review_status).icon" class="h-5 w-5 shrink-0" :class="reviewStyle(item.review_status).tone" />
									<div class="flex flex-col gap-1 min-w-0">
										<div class="text-base font-normal text-gray-800">{{ __(reviewStyle(item.review_status).label) }}</div>
										<div class="text-xs font-normal text-gray-500">{{ dayjs(item.date).format("ddd, D MMM YYYY") }}</div>
										<div v-if="item.shift" class="text-xs font-normal text-gray-700">{{ __("Shift") }}: {{ shiftLabel(item.shift) }}</div>
										<div v-if="item.review_note" class="text-xs font-normal text-gray-700 line-clamp-2">{{ item.review_note }}</div>
									</div>
								</div>
								<FeatherIcon name="chevron-right" class="h-5 w-5 text-gray-500 shrink-0" />
							</router-link>
						</div>
					</div>
				</div>
			</div>
		</ion-content>
	</ion-page>
</template>

<script setup>
import { computed, inject, onMounted, reactive, ref } from "vue"
import { useRouter } from "vue-router"
import { IonContent, IonPage } from "@ionic/vue"
import { Button, FeatherIcon, createResource, toast } from "frappe-ui"

import GroomingCapture from "@/components/GroomingCapture.vue"
import { shiftLabel } from "@/data/shiftTimes"
import { canSubmit, reviewStyle, toPayload, viewState } from "@/utils/grooming"

const __ = inject("$translate")
const dayjs = inject("$dayjs")
const router = useRouter()

const status = ref(null)
const loading = ref(true)
const loadError = ref("")
const error = ref("")
const sending = ref(false)
const reviewing = ref(false)
const index = ref(0)
const photos = reactive({})

const statusResource = createResource({ url: "custom_hr.api.grooming.get_grooming_status", method: "GET", onError() {} })
const submitResource = createResource({ url: "custom_hr.api.grooming.submit_grooming", method: "POST", onError() {} })

const view = computed(() => viewState(status.value))
const history = computed(() => status.value?.history || [])
const steps = computed(() => status.value?.steps || [])
const step = computed(() => steps.value[index.value])
const ready = computed(() => canSubmit(photos, steps.value))

function message(err) {
	return err?.messages?.filter(Boolean).join("\n") || err?.message || __("Unable to send grooming. Try again.")
}

function goBack() {
	router.back()
}

function retake(position) {
	photos[steps.value[position].key] = null
	index.value = position
	reviewing.value = false
}

async function load() {
	loading.value = true
	loadError.value = ""
	try {
		status.value = await statusResource.fetch()
	} catch (err) {
		loadError.value = message(err)
	} finally {
		loading.value = false
	}
}

async function send() {
	if (!ready.value || sending.value) return
	sending.value = true
	error.value = ""
	try {
		await submitResource.submit({ photos: JSON.stringify(toPayload(photos, steps.value)) })
		toast({ title: __("Success"), text: __("Grooming sent"), icon: "check-circle", position: "bottom-center", iconClasses: "text-green-500" })
		Object.keys(photos).forEach((key) => delete photos[key])
		reviewing.value = false
		index.value = 0
		await load()
	} catch (err) {
		error.value = message(err)
		await load() // a refused duplicate shows today's real state
	} finally {
		sending.value = false
	}
}

onMounted(load)
</script>
