<template>
	<ion-page>
		<ion-content class="ion-no-padding">
			<div class="flex flex-col min-h-screen w-screen sm:w-96 bg-gray-50">
				<header class="flex flex-row bg-white shadow-sm py-4 px-3 items-center border-b sticky top-0 z-10">
					<Button variant="ghost" class="!pl-0 hover:bg-white" @click="router.back()">
						<FeatherIcon name="chevron-left" class="h-5 w-5" />
					</Button>
					<h2 class="text-xl font-semibold text-gray-900">{{ __("Grooming") }}</h2>
				</header>

				<div class="flex flex-col gap-4 p-4">
					<p v-if="loading" class="text-sm text-gray-500 text-center py-10">{{ __("Loading...") }}</p>
					<p v-else-if="error" class="text-sm text-red-600" role="alert">{{ error }}</p>

					<template v-else-if="detail">
						<div class="bg-white rounded-lg p-4 shadow-sm flex flex-col gap-3">
							<div class="flex flex-row items-start justify-between gap-2">
								<div>
									<p class="text-lg font-semibold text-gray-900">{{ dayjs(detail.date).format("dddd, D MMMM YYYY") }}</p>
									<p v-if="detail.shift" class="text-sm text-gray-500 mt-0.5">{{ __("Shift") }}: {{ shiftLabel(detail.shift) }}</p>
									<p v-if="sentAt" class="text-xs text-gray-400 mt-0.5">{{ __("Sent at {0}", [sentAt]) }}</p>
								</div>
								<span class="px-3 py-1 rounded-full text-xs font-medium whitespace-nowrap" :class="style.pill">{{ __(style.label) }}</span>
							</div>
							<div v-if="detail.review_note" class="rounded-lg bg-gray-50 p-3">
								<p class="text-xs font-medium text-gray-500 uppercase tracking-wide">{{ __("Reviewer's note") }}</p>
								<p class="text-sm text-gray-800 mt-1">{{ detail.review_note }}</p>
							</div>
							<p v-else-if="detail.review_status === 'Menunggu'" class="text-sm text-gray-500">{{ __("Waiting for the SOP team to review your photos.") }}</p>
						</div>

						<div class="bg-white rounded-lg p-4 shadow-sm flex flex-col gap-3">
							<h3 class="text-base font-semibold text-gray-900">{{ __("Photos") }}</h3>
							<div class="grid grid-cols-2 gap-3">
								<button v-for="(photo, position) in detail.photos" :key="photo.step" type="button" class="flex flex-col gap-1 text-left" @click="zoom = photo">
									<img :src="photo.photo" :alt="photo.title" loading="lazy" class="w-full aspect-[3/4] object-cover rounded-lg border border-gray-200" />
									<span class="text-xs text-gray-600">{{ position + 1 }}. {{ photo.title }}</span>
								</button>
							</div>
						</div>
					</template>
				</div>

				<div v-if="zoom" class="fixed inset-0 z-50 bg-black/90 flex flex-col items-center justify-center p-4" @click="zoom = null">
					<img :src="zoom.photo" :alt="zoom.title" class="max-h-[80vh] max-w-full rounded-lg" />
					<p class="text-sm text-gray-200 mt-3">{{ zoom.title }}</p>
					<button type="button" class="absolute top-4 right-4 h-10 w-10 rounded-full bg-white/10 text-white flex items-center justify-center" :aria-label="__('Close')" @click.stop="zoom = null">
						<FeatherIcon name="x" class="h-5 w-5" />
					</button>
				</div>
			</div>
		</ion-content>
	</ion-page>
</template>

<script setup>
import { computed, inject, onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { IonContent, IonPage } from "@ionic/vue"
import { Button, FeatherIcon, createResource } from "frappe-ui"

import { shiftLabel } from "@/data/shiftTimes"
import { reviewStyle } from "@/utils/grooming"

const props = defineProps({ id: { type: String, required: true } })

const __ = inject("$translate")
const dayjs = inject("$dayjs")
const router = useRouter()

const detail = ref(null)
const loading = ref(true)
const error = ref("")
const zoom = ref(null)

const detailResource = createResource({ url: "custom_hr.api.grooming.get_grooming_detail", method: "GET", onError() {} })

const style = computed(() => reviewStyle(detail.value?.review_status))
const sentAt = computed(() => (detail.value?.submitted_at ? dayjs(detail.value.submitted_at).format("HH:mm") : ""))

onMounted(async () => {
	try {
		detail.value = await detailResource.fetch({ name: props.id })
	} catch (err) {
		error.value = err?.messages?.filter(Boolean).join("\n") || __("Unable to load this grooming.")
	} finally {
		loading.value = false
	}
})
</script>
