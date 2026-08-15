const { test } = require('node:test');
const assert = require('node:assert');
const W = require('../js/watchcore.js');

const never = () => false;
const f = (name, size, extra = {}) => ({ name, path: '/w/' + name, size, mtimeMs: 1000, ...extra });

function run(entries, ticks, seen = never) {
  let state = {};
  let last;
  for (let i = 0; i < ticks; i++) {
    last = W.planTick(entries, state, seen);
    state = last.sizes;
  }
  return last;
}

test('a settled local file imports, but only after STABLE_TICKS observations', () => {
  const e = [f('clip.mp4', 5000)];
  assert.strictEqual(run(e, 1).ready.length, 0, 'first sighting must not import');
  assert.strictEqual(run(e, 2).ready.length, 0, 'one match is not enough');
  assert.strictEqual(run(e, 3).ready.length, 1, 'settles after STABLE_TICKS matches');
});

test('a dataless cloud placeholder never imports, however long it sits', () => {
  assert.strictEqual(run([f('online-only.mp4', 697415, { hasData: false })], 10).ready.length, 0);
});

test('a file still growing never settles', () => {
  let state = {};
  let ready = [];
  for (let size = 1000; size <= 9000; size += 1000) {
    const r = W.planTick([f('growing.mp4', size)], state, never);
    state = r.sizes;
    ready = r.ready;
  }
  assert.strictEqual(ready.length, 0);
});

test('a finished name is held back while its .part sibling still exists', () => {
  const mid = [f('clip.mp4', 5000), f('clip.mp4.part', 120)];
  assert.strictEqual(run(mid, 5).ready.length, 0, 'sibling means still assembling');
  assert.strictEqual(run([f('clip.mp4', 5000)], 3).ready.length, 1, 'imports once sibling is gone');
});

test('temp markers are still excluded by name', () => {
  assert.strictEqual(W.isCandidateName('clip.mp4.part'), false);
  assert.strictEqual(W.isCandidateName('clip.ytdl'), false);
  assert.strictEqual(W.isCandidateName('clip.mp4'), true);
});

test('zero-byte files never settle', () => {
  assert.strictEqual(run([f('empty.mp4', 0)], 5).ready.length, 0);
});

test('already-seen files are skipped entirely', () => {
  assert.strictEqual(run([f('clip.mp4', 5000)], 5, () => true).ready.length, 0);
});

test('legacy bare-number state from an older run is tolerated', () => {
  const e = [f('clip.mp4', 5000)];
  const r1 = W.planTick(e, { '/w/clip.mp4': 5000 }, never);
  assert.strictEqual(r1.ready.length, 0, 'legacy state restarts the counter, does not crash');
  assert.strictEqual(W.planTick(e, r1.sizes, never).ready.length, 1);
});

test('Windows (blocks unreported) still imports normally', () => {
  assert.strictEqual(run([f('clip.mp4', 5000, { hasData: undefined })], 3).ready.length, 1);
});
