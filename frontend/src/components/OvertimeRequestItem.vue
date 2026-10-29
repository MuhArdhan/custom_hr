<template>
	<ListItem :isTeamRequest="false">
		<template #left>
			<OvertimeIcon class="h-5 w-5 text-gray-500" />
			<div class="flex flex-col items-start gap-1.5">
				<div class="text-base font-normal text-gray-800">{{ props.doc.overtime_type }}</div>
				<div class="text-xs font-normal text-gray-500">
					<span>{{ dayjs(props.doc.date).format("D MMM") }}</span>
					<span class="whitespace-pre"> &middot; </span>
					<span class="whitespace-nowrap">{{ props.doc.start_time.slice(0, 5) }} - {{ props.doc.end_time.slice(0, 5) }}</span>
				</div>
			</div>
		</template>
		<template #right>
			<Badge variant="outline" :theme="overtimeStatusTheme(props.doc.status)" :label="__(listStatus(props.doc.status))" size="md" />
			<FeatherIcon name="chevron-right" class="h-5 w-5 text-gray-500" />
		</template>
	</ListItem>
</template>

<script setup>
import { inject } from "vue"
import { Badge, FeatherIcon } from "frappe-ui"

import ListItem from "@/components/ListItem.vue"
import OvertimeIcon from "@/components/icons/OvertimeIcon.vue"
import { overtimeStatusTheme } from "@/data/overtime"
import { listStatus } from "@/utils/requestStatus"

const dayjs = inject("$dayjs")
const props = defineProps({
	doc: { type: Object },
	isTeamRequest: { type: Boolean, default: false },
	workflowStateField: { type: String, required: false },
})
</script>
