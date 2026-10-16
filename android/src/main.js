import { Capacitor, CapacitorHttp, registerPlugin } from "@capacitor/core"
import { Geolocation } from "@capacitor/geolocation"
import { serverOrigin, requireSafeDevice, requireCheckin } from "./policy.js"
import "./style.css"

const DevicePolicy = registerPlugin("DevicePolicy")
const $ = (id) => document.getElementById(id)
let session = null
let busy = false
const api = "custom_hr.api.checkin."

function androidOnly() {
  if (!Capacitor.isNativePlatform() || Capacitor.getPlatform() !== "android") {
    throw new Error("Fitur ini hanya tersedia di APK Android, bukan browser.")
  }
}

function render() {
  document.querySelectorAll("button, input").forEach((element) => { element.disabled = busy })
  $("checkin").disabled = busy || !session
  $("disconnect").disabled = busy || !session
}

async function run(action) {
  if (busy) return
  busy = true
  render()
  try { await action() }
  catch (error) { $("status").textContent = error.message || "Operasi gagal." }
  finally { busy = false; render() }
}

async function request(connection, method, data = {}, verb = "GET") {
  const response = await CapacitorHttp.request({
    url: `${connection.origin}/api/method/${method}`,
    method: verb,
    headers: {
      Authorization: `token ${connection.key}:${connection.secret}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    ...(verb === "GET" ? { params: data } : { data }),
    connectTimeout: 15000,
    readTimeout: 30000,
    disableRedirects: true,
  })
  if (response.status < 200 || response.status >= 300) {
    // Do not display server HTML, tracebacks, or credentials.
    const error = new Error(`Server menolak permintaan (HTTP ${response.status}). Periksa akun, izin, jadwal, radius, dan kewajiban verifikasi wajah.`)
    error.response = { status: response.status }
    throw error
  }
  if (!response.data || typeof response.data !== "object") throw new Error("Respons server tidak valid.")
  return response.data.message
}

async function inspect() {
  androidOnly()
  $("device").textContent = "Memeriksa perangkat…"
  try {
    const state = await DevicePolicy.getStatus()
    $("device").textContent = `Opsi Pengembang: ${state.developerOptionsEnabled ? "AKTIF — check-in diblokir" : "mati"}`
    requireSafeDevice(state)
  } catch (error) {
    $("device").textContent = "Perangkat belum lolos pemeriksaan."
    throw error
  }
}

$("connection").addEventListener("submit", (event) => {
  event.preventDefault()
  run(async () => {
    androidOnly()
    if (session?.submission.pending) throw new Error("Selesaikan permintaan yang belum pasti sebelum mengganti akun.")
    session = null
    $("account").textContent = "Belum terhubung."
    const connection = {
      origin: serverOrigin($("server").value),
      key: $("api-key").value.trim(), secret: $("api-secret").value.trim(),
    }
    const context = await request(connection, `${api}get_checkin_context`)
    if (!context?.employee) throw new Error("Akun tidak memiliki konteks karyawan yang valid.")
    // Reuse the existing web client's persisted UUID and recovery lifecycle.
    const { CheckinSubmission } = await import("../../frontend/src/utils/checkin.js")
    const storage = {
      getItem: (key) => localStorage.getItem(`${connection.origin}:${key}`),
      setItem: (key, value) => localStorage.setItem(`${connection.origin}:${key}`, value),
      removeItem: (key) => localStorage.removeItem(`${connection.origin}:${key}`),
    }
    session = { ...connection, submission: new CheckinSubmission(context.employee, storage, crypto) }
    $("api-key").value = ""
    $("api-secret").value = ""
    $("account").textContent = `Karyawan: ${context.employee}`
    $("status").textContent = session.submission.pending
      ? "Ada permintaan belum pasti. Tekan Check-in untuk memeriksa hasilnya terlebih dahulu."
      : "Terhubung. Tekan Check-in untuk memeriksa perangkat dan mengirim absensi."
  })
})

$("inspect").addEventListener("click", () => run(async () => {
  await inspect()
  $("status").textContent = "Pemeriksaan perangkat lolos."
}))

$("settings").addEventListener("click", () => run(async () => {
  androidOnly()
  await DevicePolicy.openSettings()
}))

$("disconnect").addEventListener("click", () => run(async () => {
  // Pending request IDs deliberately survive disconnect/restart; credentials do not.
  session = null
  $("account").textContent = "Belum terhubung."
  $("status").textContent = "Koneksi diputus. Kredensial di memori telah dilepas."
}))

$("checkin").addEventListener("click", () => run(async () => {
  androidOnly()
  const connection = session
  if (!connection) throw new Error("Hubungkan akun terlebih dahulu.")
  const submission = connection.submission
  if (submission.pending) {
    const result = await submission.recover((request_id) => request(connection, `${api}get_checkin_request_result`, { request_id }))
    if (result) {
      $("status").textContent = `Check-in terkonfirmasi: ${result.name} · ${result.time}`
      return
    }
    // Do not retry a prior-day IN with a new server timestamp, or create another UUID.
    throw new Error("Hasil permintaan sebelumnya belum ditemukan. Jangan membuat absensi baru; periksa lagi nanti atau hubungi HR. ID permintaan tetap disimpan.")
  }
  await inspect()
  const context = await request(connection, `${api}get_checkin_context`)
  requireCheckin(context)
  $("status").textContent = "Mengambil GPS…"
  const position = await Geolocation.getCurrentPosition({ enableHighAccuracy: true, timeout: 20000, maximumAge: 0 })
  const { latitude, longitude, accuracy } = position.coords
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) throw new Error("Koordinat GPS tidak valid.")
  if (!Number.isFinite(position.timestamp) || Math.abs(Date.now() - position.timestamp) > 60000) throw new Error("Lokasi GPS kedaluwarsa. Coba lagi di area dengan sinyal GPS baik.")
  // Recheck after the permission dialog / returning from Android Settings.
  await inspect()
  await request(connection, `${api}validate_checkin_location`, { latitude, longitude, log_type: "IN" }, "POST")
  await inspect()
  submission.begin("IN", "standard", { workDate: context.shift_work_date })
  $("status").textContent = "Mengirim check-in…"
  const result = await submission.submit(
    (data) => request(connection, `${api}submit_checkin`, data, "POST"),
    { latitude, longitude },
  )
  $("status").textContent = `Check-in berhasil: ${result.name} · ${result.time} · Akurasi GPS ±${Math.round(accuracy)} m`
}))

render()
