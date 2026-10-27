// Helpers for the Grooming screen: five photos, one per SOP step, sent together.

// Scale so the long side is at most `max`; never upscale.
export function fitWithin(width, height, max) {
	const scale = Math.min(1, max / Math.max(width, height))
	return { width: Math.round(width * scale), height: Math.round(height * scale) }
}

// photos is { [step.key]: dataUrl }
export function nextStep(photos, steps) {
	const index = steps.findIndex((step) => !photos[step.key])
	return index === -1 ? null : index
}

export function canSubmit(photos, steps) {
	return steps.length > 0 && steps.every((step) => !!photos[step.key])
}

export function toPayload(photos, steps) {
	return steps.map((step) => photos[step.key])
}

// What the Grooming screen shows: the history once today's grooming is sent, a prompt until the employee
// has checked in, and the camera flow otherwise.
export function viewState(status) {
	if (!status) return "loading"
	if (status.submitted) return "history"
	return status.checked_in ? "capture" : "needs_checkin"
}

// History is newest first; keep that order and start a new group when the month changes.
export function groupByMonth(items) {
	const groups = []
	for (const item of items) {
		const month = String(item.date).slice(0, 7)
		const last = groups[groups.length - 1]
		if (last?.month === month) last.items.push(item)
		else groups.push({ month, items: [item] })
	}
	return groups
}

export function historySummary(items) {
	const summary = { Sesuai: 0, "Tidak Sesuai": 0, Menunggu: 0 }
	for (const item of items) summary[item.review_status in summary ? item.review_status : "Menunggu"]++
	return summary
}

export const reviewStyle = (result) =>
	({
		Sesuai: { label: "Compliant", pill: "bg-green-50 text-green-700", bar: "border-green-500", icon: "check-circle", tone: "text-green-600" },
		"Tidak Sesuai": { label: "Not compliant", pill: "bg-red-50 text-red-700", bar: "border-red-500", icon: "x-circle", tone: "text-red-600" },
	})[result] || { label: "Pending review", pill: "bg-orange-50 text-orange-700", bar: "border-orange-400", icon: "clock", tone: "text-orange-600" }
