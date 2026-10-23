import { createResource } from "frappe-ui"

export const settings = createResource({
	url: "custom_hr.api.get_hr_settings",
	method: "GET",
	auto: true,
})
