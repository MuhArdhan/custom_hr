// Pending workflow stages ("Menunggu PL", "Menunggu HRD", ...) read just "Menunggu" in lists;
// the detail view names who the request waits for.
export const isWaiting = (state) => typeof state === "string" && state.startsWith("Menunggu")

export const listStatus = (state) => (isWaiting(state) ? "Menunggu" : state)

export const waitingLabel = (state, name) => (isWaiting(state) && name ? `Menunggu ${name}` : state)

// Leave: the PL/SPV (outlet) and Approver 1/2 (department) stages wait for the leave approver; Menunggu HRD already says who.
export const leaveDetailStatus = (doc, stateField) => {
	const state = stateField ? doc?.[stateField] : null
	if (!isWaiting(state)) return null
	return ["Menunggu PL", "Menunggu SPV", "Menunggu Approver 1", "Menunggu Approver 2"].includes(state) ? waitingLabel(state, doc.leave_approver_name || doc.leave_approver) : state
}
