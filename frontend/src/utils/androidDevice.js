// Capacitor injects this native plugin into the remote HRMS WebView.
// Ordinary browsers retain the existing web attendance flow.
export async function requireAndroidAttendanceDevice(host = window) {
	const capacitor = host.Capacitor
	if (!capacitor?.isNativePlatform?.()) return
	if (capacitor.getPlatform?.() !== "android") return
	const plugin = capacitor.Plugins?.DevicePolicy
	if (!plugin?.getStatus) {
		throw new Error("Pemeriksaan perangkat Android tidak tersedia. Perbarui aplikasi sebelum melakukan absensi.")
	}
	let status
	try {
		status = await plugin.getStatus()
	} catch {
		throw new Error("Tidak dapat memeriksa Opsi Pengembang. Absensi diblokir; coba lagi.")
	}
	if (status?.developerOptionsEnabled !== false) {
		throw new Error("Absensi diblokir. Matikan Opsi Pengembang di pengaturan Android, lalu coba lagi.")
	}
}
