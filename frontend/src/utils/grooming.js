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
