<template>
	<ListItem>
		<template #left>
			<FeatherIcon name="clock" class="h-5 w-5 text-gray-500" />
			<div class="flex flex-col items-start gap-1.5">
				<div class="text-base font-normal text-gray-800">
					{{ __("Log Type: {0}", [props.doc.log_type]) }}
				</div>
				<div class="text-xs font-normal text-gray-500">
					<span>{{ formatSiteDateTime(props.doc.time) }}</span>
					<span v-if="props.doc.face_verified" class="ml-1 text-green-600">
						&middot; {{ __("Face Verified") }}
					</span>
				</div>
				<div v-if="props.doc.shift" class="text-xs text-gray-700">{{ __("Shift") }}: {{ props.doc.shift }}</div>
				<div v-if="props.doc.outlet_at_checkin" class="text-xs text-gray-500">{{ __("Outlet") }}: {{ props.doc.outlet_at_checkin }}</div>
				<div v-if="props.doc.shift_work_date" class="text-xs text-gray-500">{{ __("Work Date") }}: {{ props.doc.shift_work_date }}</div>
				<div v-if="props.doc.checkout_deadline && props.doc.log_type === 'IN'" class="text-xs text-gray-500">{{ __("Check-out Deadline") }}: {{ formatSiteDateTime(props.doc.checkout_deadline) }}</div>
				<div
					v-if="hasCoordinates(props.doc.latitude, props.doc.longitude)"
					class="text-xs font-normal text-gray-500"
				>
					{{ Number(props.doc.latitude).toFixed(5) }}, {{ Number(props.doc.longitude).toFixed(5) }}
				</div>
			</div>
		</template>
		<template #right>
			<img
				v-if="props.doc.face_photo"
				:src="props.doc.face_photo"
				class="h-10 w-10 rounded-lg object-cover border border-gray-200"
			/>
			<FeatherIcon name="chevron-right" class="h-5 w-5 text-gray-500" />
		</template>
	</ListItem>
</template>

<script setup>
import { FeatherIcon } from "frappe-ui"
import { inject } from "vue"

import ListItem from "@/components/ListItem.vue"
import { formatSiteDateTime, hasCoordinates } from "@/utils/checkin"

const __ = inject("$translate")

const props = defineProps({
	doc: {
		type: Object,
	},
})
</script>
