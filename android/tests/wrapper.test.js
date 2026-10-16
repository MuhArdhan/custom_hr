import test from "node:test"
import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"
import { requireAndroidAttendanceDevice } from "../../frontend/src/utils/androidDevice.js"

const android = (getStatus) => ({ Capacitor: {
  isNativePlatform: () => true,
  getPlatform: () => "android",
  Plugins: getStatus ? { DevicePolicy: { getStatus } } : {},
} })

test("wrapper loads the existing HTTPS HRMS, without wildcard navigation", async () => {
  const config = JSON.parse(await readFile(new URL("../capacitor.config.json", import.meta.url)))
  assert.equal(config.server.url, "https://sea-beyond-expansion-respond.trycloudflare.com/hrms")
  assert.equal(config.server.cleartext, false)
  assert.equal(config.server.allowNavigation, undefined)
})

test("ordinary browsers keep the existing attendance flow", async () => {
  await requireAndroidAttendanceDevice({})
  await requireAndroidAttendanceDevice({ Capacitor: { isNativePlatform: () => false } })
})

test("Android only passes an explicitly disabled developer setting", async () => {
  await requireAndroidAttendanceDevice(android(async () => ({ developerOptionsEnabled: false })))
  for (const value of [true, undefined, 0]) {
    await assert.rejects(requireAndroidAttendanceDevice(android(async () => ({ developerOptionsEnabled: value }))), /Matikan Opsi Pengembang/)
  }
})

test("missing native plugin or unreadable setting fails closed", async () => {
  await assert.rejects(requireAndroidAttendanceDevice(android()), /tidak tersedia/)
  await assert.rejects(requireAndroidAttendanceDevice(android(async () => { throw new Error("denied") })), /Absensi diblokir/)
})
