import { createListResource } from "frappe-ui"

export const shiftTypes = createListResource({
	doctype: "Shift Type",
	fields: ["name", "start_time", "end_time"],
	pageLength: 1000,
	cache: "custom_hr:shift_times",
	auto: true,
})

const hourMinute = (time) => String(time).split(":").slice(0, 2).join(":")

// "Shift Pagi" -> "08:00 - 16:00"; falls back to the name until the times are loaded
export const shiftLabel = (name) => {
	const shift = shiftTypes.data?.find((row) => row.name === name)
	return shift ? `${hourMinute(shift.start_time)} - ${hourMinute(shift.end_time)}` : name
}
