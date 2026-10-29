<template>
	<!-- Built from the API row: the employee cannot read the Overtime Request document itself. -->
	<div v-if="props.modelValue" class="bg-white w-full flex flex-col items-center justify-center pb-5 max-h-[calc(100vh-5rem)]">
		<div class="w-full flex flex-row gap-2 pt-8 pb-5 border-b justify-center items-center sticky top-0 z-[100]">
			<span class="text-gray-900 font-bold text-lg text-center">{{ __("Overtime Request") }}</span>
		</div>
		<div class="w-full p-4 overflow-auto">
			<div class="flex flex-col items-center justify-center gap-5">
				<div v-for="row in rows" :key="row.label" :class="[row.block ? 'flex-col gap-1' : 'flex-row items-center justify-between', 'flex w-full']">
					<div class="text-gray-600 text-base">{{ __(row.label) }}</div>
					<Badge v-if="row.status" variant="outline" :theme="overtimeStatusTheme(row.value)" :label="__(row.value)" size="md" />
					<div v-else class="text-base text-gray-900" :class="row.block ? 'whitespace-pre-wrap' : ''">{{ row.value }}</div>
				</div>
			</div>
		</div>
		<div v-if="props.modelValue.can_cancel" class="flex w-full flex-row items-center justify-between gap-3 sticky bottom-0 border-t z-[100] p-4">
			<Button class="w-full py-5" variant="subtle" theme="red" :loading="cancelling" @click="cancel">
				<template #prefix><FeatherIcon name="x" class="w-4" /></template>
				{{ __("Cancel") }}
			</Button>
		</div>
	</div>
</template>

<script setup>
import { computed, inject, ref } from "vue"
import { modalController } from "@ionic/vue"
import { Badge, Button, FeatherIcon, createResource, toast } from "frappe-ui"

import { myOvertime, overtimeStatusTheme } from "@/data/overtime"
import { waitingLabel } from "@/utils/requestStatus"

const __ = inject("$translate")
const dayjs = inject("$dayjs")
const props = defineProps({ modelValue: { type: Object, required: true } })

const cancelling = ref(false)
const cancelResource = createResource({ url: "custom_hr.api.my_overtime.cancel_my_overtime", method: "POST", onError() {} })

const rows = computed(() => {
	const doc = props.modelValue
	return [
		{ label: "ID", value: doc.name },
		{ label: "Overtime Type", value: doc.overtime_type },
		{ label: "Date", value: dayjs(doc.date).format("D MMM YYYY") },
		{ label: "Time", value: `${doc.start_time.slice(0, 5)} - ${doc.end_time.slice(0, 5)}` },
		{ label: "Hours", value: doc.planned_hours },
		{ label: "Status", value: waitingLabel(doc.status, doc.waiting_for), status: true },
		{ label: "Reason", value: doc.reason, block: true },
	]
})

async function cancel() {
	if (cancelling.value || !window.confirm(__("Cancel this overtime request?"))) return
	cancelling.value = true
	try {
		await cancelResource.submit({ name: props.modelValue.name })
		toast({ title: __("Success"), text: __("Overtime request cancelled"), icon: "check-circle", position: "bottom-center", iconClasses: "text-green-500" })
		await modalController.dismiss()
	} catch (err) {
		const text = err?.messages?.filter(Boolean).join("\n") || __("Unable to cancel.")
		toast({ title: __("Error"), text, icon: "alert-circle", position: "bottom-center", iconClasses: "text-red-500" })
	} finally {
		cancelling.value = false
		myOvertime.reload()
	}
}
</script>
