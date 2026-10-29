<template>
	<ion-page>
		<ion-content class="ion-no-padding">
			<div class="flex flex-col min-h-screen w-screen sm:w-96 bg-gray-50">
				<header class="flex flex-row bg-white shadow-sm py-4 px-3 items-center border-b sticky top-0 z-10">
					<Button variant="ghost" class="!pl-0 hover:bg-white" @click="router.back()">
						<FeatherIcon name="chevron-left" class="h-5 w-5" />
					</Button>
					<h2 class="text-xl font-semibold text-gray-900">{{ __("Request Overtime") }}</h2>
				</header>

				<div class="flex flex-col gap-4 p-4">
					<p v-if="loading" class="text-sm text-gray-500 text-center py-10">{{ __("Loading...") }}</p>
					<p v-else-if="loadError" class="text-sm text-red-600" role="alert">{{ loadError }}</p>

					<form v-else class="bg-white rounded-lg p-4 shadow-sm flex flex-col gap-3" @submit.prevent="send">
						<label class="flex flex-col gap-1 text-xs text-gray-600">
							{{ __("Overtime Type") }}
							<select v-model="form.overtime_type" required class="rounded border border-gray-300 px-2 py-2 text-sm text-gray-900">
								<option value="" disabled>{{ __("Select overtime type") }}</option>
								<option v-for="type in state.overtime_types" :key="type.name" :value="type.name">{{ type.name }}</option>
							</select>
						</label>
						<label class="flex flex-col gap-1 text-xs text-gray-600">
							{{ __("Date") }}
							<input v-model="form.date" type="date" :min="state.min_date" :max="state.max_date" required class="rounded border border-gray-300 px-2 py-2 text-sm text-gray-900" />
						</label>
						<div class="flex gap-3">
							<label class="flex flex-col gap-1 flex-1 text-xs text-gray-600">
								{{ __("Start") }}
								<input v-model="form.start_time" type="time" required class="rounded border border-gray-300 px-2 py-2 text-sm text-gray-900" />
							</label>
							<label class="flex flex-col gap-1 flex-1 text-xs text-gray-600">
								{{ __("End") }}
								<input v-model="form.end_time" type="time" required class="rounded border border-gray-300 px-2 py-2 text-sm text-gray-900" />
							</label>
						</div>
						<label class="flex flex-col gap-1 text-xs text-gray-600">
							{{ __("Reason") }}
							<textarea v-model="form.reason" rows="3" required class="rounded border border-gray-300 px-2 py-2 text-sm text-gray-900" />
						</label>
						<p v-if="maxHours" class="text-xs text-gray-500">{{ __("Maximum {0} hours for {1}.", [maxHours, form.overtime_type]) }}</p>
						<p v-if="error" class="text-sm text-red-600" role="alert">{{ error }}</p>
						<Button type="submit" variant="solid" class="w-full py-5 text-base" :loading="sending" :disabled="!ready">
							{{ __("Submit") }}
						</Button>
					</form>
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

import { myOvertime } from "@/data/overtime"

const __ = inject("$translate")
const router = useRouter()

const state = computed(() => myOvertime.data)
const loading = ref(true)
const loadError = ref("")
const error = ref("")
const sending = ref(false)
const form = reactive({ overtime_type: "", date: "", start_time: "", end_time: "", reason: "" })

const submitResource = createResource({ url: "custom_hr.api.my_overtime.submit_my_overtime", method: "POST", onError() {} })

const maxHours = computed(() => state.value?.overtime_types?.find((type) => type.name === form.overtime_type)?.max_hours || 0)
const ready = computed(() => form.overtime_type && form.date && form.start_time && form.end_time && form.reason.trim() && !sending.value)

function message(err, fallback) {
	return err?.messages?.filter(Boolean).join("\n") || err?.message || fallback
}

async function load() {
	try {
		const data = await myOvertime.reload()
		form.date ||= data.min_date
		form.overtime_type ||= data.default_overtime_type || ""
	} catch (err) {
		loadError.value = message(err, __("Unable to load overtime."))
	} finally {
		loading.value = false
	}
}

async function send() {
	if (!ready.value) return
	sending.value = true
	error.value = ""
	try {
		await submitResource.submit({ ...form })
		toast({ title: __("Success"), text: __("Overtime request sent"), icon: "check-circle", position: "bottom-center", iconClasses: "text-green-500" })
		Object.assign(form, { start_time: "", end_time: "", reason: "" })
		myOvertime.reload()
		router.back() // the new request shows under My Requests
	} catch (err) {
		error.value = message(err, __("Unable to send the overtime request. Try again."))
	} finally {
		sending.value = false
	}
}

onMounted(load)
</script>
