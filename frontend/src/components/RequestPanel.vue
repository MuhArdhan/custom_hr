<template>
	<div class="w-full">
		<div class="text-lg text-gray-800 font-bold">{{ __("My Requests") }}</div>
		<RequestList :items="myRequests" />
	</div>
</template>

<script setup>
import { inject, computed, markRaw } from "vue"

import RequestList from "@/components/RequestList.vue"

import { myAttendanceRequests, myShiftRequests } from "@/data/attendance"
import { myClaims } from "@/data/claims"
import { myLeaves } from "@/data/leaves"
import { myOvertime } from "@/data/overtime"

import AttendanceRequestItem from "@/components/AttendanceRequestItem.vue"
import ExpenseClaimItem from "@/components/ExpenseClaimItem.vue"
import LeaveRequestItem from "@/components/LeaveRequestItem.vue"
import ShiftRequestItem from "@/components/ShiftRequestItem.vue"
import OvertimeRequestItem from "@/components/OvertimeRequestItem.vue"

const __ = inject("$translate")

const myRequests = computed(() =>
	updateRequestDetails(myLeaves, myClaims, myShiftRequests, myAttendanceRequests, { data: myOvertime.data?.history })
)

function updateRequestDetails(leaves, claims, shiftRequests, attendanceRequests, overtime = null) {
	const requests = [leaves, claims, shiftRequests, attendanceRequests, overtime].reduce(
		(acc, resource) => acc.concat(resource?.data || []),
		[]
	)

	const componentMap = {
		"Leave Application": LeaveRequestItem,
		"Expense Claim": ExpenseClaimItem,
		"Shift Request": ShiftRequestItem,
		"Attendance Request": AttendanceRequestItem,
		"Overtime Request": OvertimeRequestItem,
	}
	requests.forEach((request) => {
		request.component = markRaw(componentMap[request.doctype])
	})

	return getSortedRequests(requests)
}

function getSortedRequests(list) {
	// return top 10 requests sorted by posting date
	return list
		.sort((a, b) => {
			return new Date(b.creation) - new Date(a.creation)
		})
		.splice(0, 10)
}
</script>
