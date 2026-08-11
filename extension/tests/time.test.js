// Run with: node --test extension/tests/
const test = require("node:test");
const assert = require("node:assert");
const t = require("../content/time.js");

test("fmtClock", () => {
  assert.equal(t.fmtClock(78.4), "1:18");
  assert.equal(t.fmtClock(5), "0:05");
  assert.equal(t.fmtClock(0), "0:00");
  assert.equal(t.fmtClock(3723), "1:02:03");
  assert.equal(t.fmtClock(-3), "0:00");
  assert.equal(t.fmtClock(undefined), "0:00");
});

test("fmtClockTenths", () => {
  assert.equal(t.fmtClockTenths(78.46), "1:18.4");
  assert.equal(t.fmtClockTenths(0), "0:00.0");
  assert.equal(t.fmtClockTenths(59.99), "0:59.9");
});

test("fmtDuration", () => {
  assert.equal(t.fmtDuration(36.34), "36.3s");
  assert.equal(t.fmtDuration(2), "2s");
  assert.equal(t.fmtDuration(96), "1:36");
  assert.equal(t.fmtDuration(0), "0s");
});
