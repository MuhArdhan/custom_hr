export function serverOrigin(value) {
  const url = new URL(value.trim())
  if (url.protocol !== "https:" || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("Gunakan origin HTTPS saja, misalnya https://hr.example.com tanpa path.")
  }
  return url.origin
}

export function requireSafeDevice(state) {
  if (state?.developerOptionsEnabled !== false) {
    throw new Error("Check-in diblokir. Matikan Opsi Pengembang di pengaturan Android, lalu coba lagi.")
  }
}

export function requireCheckin(context) {
  if (!context?.employee || context.allowed !== true || context.next_action !== "IN") {
    throw new Error(context?.message || "Check-in tidak tersedia. Prototipe ini belum mendukung check-out.")
  }
}
