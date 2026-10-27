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

					<!-- Already sent today -->
					<div v-else-if="status?.submitted" class="bg-white rounded-lg p-6 shadow-sm flex flex-col items-center text-center gap-3">
						<div class="h-14 w-14 rounded-full bg-green-50 flex items-center justify-center">
							<FeatherIcon name="check" class="h-7 w-7 text-green-600" />
						</div>
						<h3 class="text-lg font-semibold text-gray-900">{{ __("Today's grooming has been sent") }}</h3>
						<span class="px-3 py-1 rounded-full text-sm font-medium" :class="review.pill">{{ review.label }}</span>
						<p v-if="status.review_note" class="w-full text-left text-sm text-gray-700 bg-gray-50 rounded-lg p-3">{{ status.review_note }}</p>
					</div>

					<!-- Review all five photos, then send -->
					<div v-else-if="reviewing" class="bg-white rounded-lg p-4 shadow-sm flex flex-col gap-4">
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
					<div v-else-if="step" class="bg-white rounded-lg p-4 shadow-sm flex flex-col gap-4">
						<div class="flex flex-row gap-1" role="progressbar" :aria-valuenow="index + 1" :aria-valuemax="steps.length">
							<div v-for="(item, position) in steps" :key="item.key" class="h-1.5 flex-1 rounded-full" :class="position === index ? 'bg-gray-800' : photos[item.key] ? 'bg-green-500' : 'bg-gray-200'" />
						</div>
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
import { canSubmit, toPayload } from "@/utils/grooming"

const __ = inject("$translate")
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

const steps = computed(() => status.value?.steps || [])
const step = computed(() => steps.value[index.value])
const ready = computed(() => canSubmit(photos, steps.value))
const review = computed(() => {
	const result = status.value?.review_status
	if (result === "Sesuai") return { label: __("Compliant"), pill: "bg-green-50 text-green-700" }
	if (result === "Tidak Sesuai") return { label: __("Not compliant"), pill: "bg-red-50 text-red-700" }
	return { label: __("Pending review"), pill: "bg-orange-50 text-orange-700" }
})

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
