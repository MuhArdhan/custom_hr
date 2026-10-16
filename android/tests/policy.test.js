import test from "node:test"
import assert from "node:assert/strict"
import { serverOrigin, requireSafeDevice, requireCheckin } from "../src/policy.js"

test("only HTTPS origins without credentials/paths are accepted", () => {
  assert.equal(serverOrigin(" https://hr.example.com/ "), "https://hr.example.com")
  for (const value of ["http://hr.example.com", "https://user:pass@hr.example.com", "https://hr.example.com/hrms", "https://hr.example.com/?x=1", "https://hr.example.com/#x"]) {
    assert.throws(() => serverOrigin(value))
  }
})

test("device policy fails closed, including missing native results", () => {
  assert.doesNotThrow(() => requireSafeDevice({ developerOptionsEnabled: false }))
  for (const state of [undefined, {}, { developerOptionsEnabled: true }, { developerOptionsEnabled: 0 }]) {
    assert.throws(() => requireSafeDevice(state))
  }
})

test("only an explicitly allowed IN can be submitted", () => {
  assert.doesNotThrow(() => requireCheckin({ employee: "EMP-1", allowed: true, next_action: "IN" }))
  for (const context of [null, {}, { employee: "EMP-1", allowed: true, next_action: "OUT" }, { employee: "EMP-1", allowed: false, next_action: "IN" }]) {
    assert.throws(() => requireCheckin(context))
  }
})
