// node --test premiere/tests/watchcore.test.js
// Pure watcher logic: candidate filter, readiness gate, dedupe keys.
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const W = require("../js/watchcore.js");

function entry(name, size, mtimeMs) {
  return { name: name, path: "/footage/" + name, size: size, mtimeMs: mtimeMs || 1000 };
}

test("isCandidateName accepts video extensions, any case", () => {
  assert.ok(W.isCandidateName("clip.mp4"));
  assert.ok(W.isCandidateName("Clip.MOV"));
  assert.ok(W.isCandidateName("a.mkv"));
  assert.ok(W.isCandidateName("b.webm"));
  assert.ok(W.isCandidateName("c.m4v"));
});

test("isCandidateName rejects non-video and in-flight files", () => {
  assert.ok(!W.isCandidateName("notes.txt"));
  assert.ok(!W.isCandidateName("clip.mp4.part"));
  assert.ok(!W.isCandidateName("clip.part-Frag1.mp4"));
  assert.ok(!W.isCandidateName("clip.mp4.ytdl"));
  assert.ok(!W.isCandidateName("clip.h264tmp.mp4"));
  assert.ok(!W.isCandidateName("clip"));
  assert.ok(!W.isCandidateName(".mp4")); // hidden/no stem
});

test("dedupeKey includes path, size and mtime", () => {
  const k = W.dedupeKey("/f/a.mp4", 100, 5000.7);
  assert.strictEqual(k, "/f/a.mp4|100|5001");
  assert.notStrictEqual(k, W.dedupeKey("/f/a.mp4", 100, 9000));
  assert.notStrictEqual(k, W.dedupeKey("/f/a.mp4", 101, 5000.7));
});

test("planTick: new file waits one tick, imports when size is stable", () => {
  const seen = () => false;
  const first = W.planTick([entry("a.mp4", 100)], {}, seen);
  assert.deepStrictEqual(first.ready, []);
  assert.strictEqual(first.sizes["/footage/a.mp4"], 100);

  const second = W.planTick([entry("a.mp4", 100)], first.sizes, seen);
  assert.strictEqual(second.ready.length, 1);
  assert.strictEqual(second.ready[0].path, "/footage/a.mp4");
});

test("planTick: growing file stays pending until stable", () => {
  const seen = () => false;
  let sizes = W.planTick([entry("a.mp4", 100)], {}, seen).sizes;
  const grew = W.planTick([entry("a.mp4", 250)], sizes, seen);
  assert.deepStrictEqual(grew.ready, []);
  assert.strictEqual(grew.sizes["/footage/a.mp4"], 250);
  const stable = W.planTick([entry("a.mp4", 250)], grew.sizes, seen);
  assert.strictEqual(stable.ready.length, 1);
});

test("planTick: zero-size files never become ready", () => {
  const seen = () => false;
  let sizes = W.planTick([entry("a.mp4", 0)], {}, seen).sizes;
  const again = W.planTick([entry("a.mp4", 0)], sizes, seen);
  assert.deepStrictEqual(again.ready, []);
});

test("planTick: seen keys are skipped entirely", () => {
  const key = W.dedupeKey("/footage/a.mp4", 100, 1000);
  const seen = (k) => k === key;
  let sizes = W.planTick([entry("a.mp4", 100)], {}, seen).sizes;
  const second = W.planTick([entry("a.mp4", 100)], sizes, seen);
  assert.deepStrictEqual(second.ready, []);
});

test("planTick: same path re-downloaded (new mtime) is not deduped", () => {
  const oldKey = W.dedupeKey("/footage/a.mp4", 100, 1000);
  const seen = (k) => k === oldKey;
  const fresh = entry("a.mp4", 100, 7777);
  let sizes = W.planTick([fresh], {}, seen).sizes;
  const second = W.planTick([fresh], sizes, seen);
  assert.strictEqual(second.ready.length, 1);
});

test("planTick: temp and non-video files are ignored", () => {
  const seen = () => false;
  const entries = [entry("a.mp4.part", 100), entry("notes.txt", 5), entry("b.h264tmp.mp4", 9)];
  const p = W.planTick(entries, {}, seen);
  assert.deepStrictEqual(p.ready, []);
  assert.deepStrictEqual(p.sizes, {});
});

test("planTick: batch — several files can become ready in one tick", () => {
  const seen = () => false;
  const es = [entry("a.mp4", 10), entry("b.mov", 20)];
  const sizes = W.planTick(es, {}, seen).sizes;
  const p = W.planTick(es, sizes, seen);
  assert.strictEqual(p.ready.length, 2);
});

test("pruneKeys keeps the most recent entries", () => {
  const keys = [];
  for (let i = 0; i < 600; i++) keys.push("k" + i);
  const pruned = W.pruneKeys(keys, 500);
  assert.strictEqual(pruned.length, 500);
  assert.strictEqual(pruned[0], "k100");
  assert.strictEqual(pruned[pruned.length - 1], "k599");
});
