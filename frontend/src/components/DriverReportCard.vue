<template>
	<router-link
		v-if="status"
		:to="{ name: 'DriverReportView' }"
		class="flex flex-row w-full items-center gap-3 rounded-lg p-4 shadow-sm"
		:class="status.submitted ? 'bg-white' : status.open ? 'bg-orange-50 border border-orange-300' : 'bg-white'"
	>
		<FeatherIcon
			:name="status.submitted ? 'check-circle' : 'map-pin'"
			class="h-6 w-6 shrink-0"
			:class="status.submitted ? 'text-green-600' : status.open ? 'text-orange-600' : 'text-gray-400'"
		/>
		<div class="flex flex-col grow">
			<div class="text-base font-medium text-gray-900">{{ __("Position Report") }}</div>
			<div class="text-sm text-gray-600">
				<template v-if="status.submitted">{{ __("Sent at {0}", [dayjs(status.submitted_at).format("HH:mm")]) }}</template>
				<template v-else-if="status.open">{{ __("Send your photo and location now") }}</template>
				<template v-else>{{ __("Opens at {0}", [status.opens_at]) }}</template>
			</div>
		</div>
		<FeatherIcon name="chevron-right" class="h-5 w-5 text-gray-500 shrink-0" />
	</router-link>
</template>

<script setup>
import { inject, onMounted, ref } from "vue"
import { FeatherIcon, createResource } from "frappe-ui"

const __ = inject("$translate")
const dayjs = inject("$dayjs")
const status = ref(null)

// a failed status only hides the card: the check-in above stays usable
const resource = createResource({ url: "custom_hr.api.driver_report.get_driver_report_status", method: "GET", onError() {} })

onMounted(async () => {
	try {
		status.value = await resource.fetch()
	} catch {
		status.value = null
	}
})
</script>
