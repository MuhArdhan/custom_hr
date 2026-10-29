import { createResource } from "frappe-ui"

// The employee's own overtime: form options (types, date range) plus the request history for My Requests.
export const myOvertime = createResource({
	url: "custom_hr.api.my_overtime.get_my_overtime",
	method: "GET",
	auto: true,
	cache: "hrms:my_overtime",
	onError() {},
})

export const overtimeStatusTheme = (status) => ({ Disetujui: "green", Ditolak: "red" })[status] || "orange"
