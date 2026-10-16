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
  assert.equal(config.android.adjustMarginsForEdgeToEdge, "auto")
  assert.equal(config.appName, "ROPI HRMS")
})

test("native launcher uses ROPI HRMS and the bundled Frappe HR icon", async () => {
  const resource = async (path) => readFile(new URL(`../native/app/src/main/res/${path}`, import.meta.url), "utf8")
  const strings = await resource("values/strings.xml")
  assert.match(strings, /name="app_name">ROPI HRMS</)
  assert.match(strings, /name="title_activity_main">ROPI HRMS</)
  assert.match(await resource("values/ic_launcher_background.xml"), /#A1EEC9/)
  for (const name of ["ic_launcher", "ic_launcher_round"]) {
    assert.match(await resource(`mipmap-anydpi-v26/${name}.xml`), /@drawable\/frappe_hr_foreground/)
    assert.match(await resource(`mipmap-anydpi/${name}.xml`), /@drawable\/frappe_hr_foreground/)
  }
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
