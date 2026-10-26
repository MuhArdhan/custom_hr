// Server wall-clock values are displayed literally. Never decide actions/dates
// from Date/dayjs/browser timezone, and never submit a client timestamp.
export function formatSiteDateTime(value) {
	return typeof value === "string" ? value.replace("T", " ").slice(0, 19) : ""
}

export function hasCoordinates(latitude, longitude) {
	if ([latitude, longitude].some((v) => v == null || (typeof v === "string" && !v.trim()) || typeof v === "boolean")) return false
	const lat = Number(latitude)
	const lon = Number(longitude)
	return Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 && (lat !== 0 || lon !== 0)
}

export function validContext(context, employee) {
	return context?.employee === employee && ["IN", "OUT", "DONE"].includes(context.next_action) && typeof context.allowed === "boolean"
}

// Same-start shifts: the server lists them and the employee must pick one before an IN.
export function shiftChoices(context, action) {
	return action === "IN" && Array.isArray(context?.shift_choices) ? context.shift_choices : []
}

const clock = (value) => String(value || "").slice(0, 5)

export function shiftChoiceLabel(choice) {
	return `${choice.shift} (${clock(choice.start_time)} - ${clock(choice.end_time)})`
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function requestUUID(crypto) {
	if (crypto?.randomUUID) return crypto.randomUUID()
	if (!crypto?.getRandomValues) throw new Error("Secure request identifiers are unavailable in this browser.")
	const bytes = crypto.getRandomValues(new Uint8Array(16))
	bytes[6] = (bytes[6] & 15) | 64
	bytes[8] = (bytes[8] & 63) | 128
	const hex = [...bytes].map((v) => v.toString(16).padStart(2, "0")).join("")
	return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

// No descriptors, photos, GPS, passwords or session tokens are persisted here.
// Methods use `this` so a Vue reactive proxy can observe the state transitions.
export class CheckinSubmission {
	constructor(employee, storage, crypto) {
		this.employee = employee
		this.storage = storage
		this.crypto = crypto
		this.key = `custom_hr.checkin.attempt:${employee}`
		this.pending = null
		this.busy = false
		this.lastResult = null
		try {
			const value = JSON.parse(storage.getItem(this.key) || "null")
			if (value?.employee === employee && UUID.test(value.request_id) && ["IN", "OUT"].includes(value.log_type) && ["standard", "face"].includes(value.channel) && value.uncertain === true) {
				this.pending = {
					employee, request_id: value.request_id, log_type: value.log_type,
					channel: value.channel, uncertain: true,
					expected_checkin: typeof value.expected_checkin === "string" ? value.expected_checkin : null,
					work_date: /^\d{4}-\d{2}-\d{2}$/.test(value.work_date) ? value.work_date : null,
				}
			}
		} catch {
			// Begin must still successfully persist an attempt before any POST.
		}
	}

	save(pending) {
		try { this.storage.setItem(this.key, JSON.stringify(pending)) }
		catch { throw new Error("Browser session storage is unavailable. Allow storage or use a supported browser before submitting attendance.") }
	}

	begin(logType, channel, { checkin = null, workDate = null } = {}) {
		if (this.pending) return this.pending
		if (!["IN", "OUT"].includes(logType) || !["standard", "face"].includes(channel)) throw new Error("Invalid check-in action.")
		const pending = { employee: this.employee, log_type: logType, channel, request_id: requestUUID(this.crypto), uncertain: false, expected_checkin: logType === "OUT" ? checkin : null, work_date: workDate }
		this.save(pending)
		this.pending = pending
		return pending
	}

	clear() {
		this.pending = null
		try { this.storage.removeItem(this.key) } catch { /* replaying an old ID is safer than creating a duplicate */ }
	}

	cancelUnsent() {
		if (!this.busy && !this.pending?.uncertain) this.clear()
	}

	accept(result) {
		if (!result?.name || result.employee !== this.employee || result.log_type !== this.pending?.log_type) throw new Error("The server did not confirm this check-in request.")
		this.lastResult = result
		this.clear()
		return result
	}

	async submit(send, payload) {
		if (this.busy || !this.pending) return null
		this.busy = true
		const wasUncertain = this.pending.uncertain
		try {
			if (this.pending.log_type === "OUT" && !this.pending.expected_checkin) throw new Error("The original IN reference is missing. Refresh the request status or contact HR before retrying OUT.")
			this.pending.uncertain = true
			this.save(this.pending)
			const params = { ...payload, log_type: this.pending.log_type, request_id: this.pending.request_id }
			if (this.pending.log_type === "OUT") params.expected_checkin = this.pending.expected_checkin
			const result = await send(params)
			return this.accept(result)
		} catch (error) {
			const status = error.response?.status
			// A rejection of a retry does not prove the *original* attempt failed.
			if (!wasUncertain && status >= 400 && status < 500 && status !== 408 && status !== 429) this.clear()
			throw error
		} finally {
			this.busy = false
		}
	}

	async recover(lookup) {
		if (this.busy || !this.pending?.uncertain) return null
		this.busy = true
		try {
			const result = await lookup(this.pending.request_id)
			return result ? this.accept(result) : null
		} finally {
			this.busy = false
		}
	}
}
