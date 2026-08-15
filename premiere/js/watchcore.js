// Pure watch-folder logic — no fs, no CEP, testable with `node --test`.
// The panel (panel.js) feeds it directory listings; it decides what is ready
// to import. ES2018-conservative: this file also runs inside CEP's browser.
(function (root) {
  "use strict";

  var EXTS = { ".mp4": 1, ".mov": 1, ".mkv": 1, ".webm": 1, ".m4v": 1 };
  var TMP_MARKERS = [".part", ".ytdl", ".h264tmp"];

  // A file is a candidate only when it looks like a finished video: known
  // extension, a real stem, and no downloader/transcoder marker in the name.
  function isCandidateName(name) {
    var lower = String(name || "").toLowerCase();
    var dot = lower.lastIndexOf(".");
    if (dot <= 0) return false;
    if (!EXTS[lower.slice(dot)]) return false;
    for (var i = 0; i < TMP_MARKERS.length; i++) {
      if (lower.indexOf(TMP_MARKERS[i]) !== -1) return false;
    }
    return true;
  }

  // mtime is in the key (not path alone) so a re-download of the same name
  // re-imports after the user deleted the old project item.
  function dedupeKey(path, size, mtimeMs) {
    return path + "|" + size + "|" + Math.round(mtimeMs);
  }

  // Consecutive unchanged observations required before a file counts as
  // settled. One was too thin: a cloud-storage placeholder holds a constant
  // (full) size forever, and a stalled copy looks identical to a finished one
  // for a single tick.
  var STABLE_TICKS = 2;

  // Prior state is {path: {size, stable}}; older runs persisted a bare number,
  // so both shapes are read.
  function prevSize(v) { return v && typeof v === "object" ? v.size : v; }
  function prevStable(v) { return v && typeof v === "object" ? Number(v.stable) || 0 : 0; }

  // A downloader writing "clip.mp4.part" means "clip.mp4" is still being
  // assembled, even when the finished name already exists on disk.
  function partnerInProgress(name, byName) {
    for (var i = 0; i < TMP_MARKERS.length; i++) {
      if (byName[(name + TMP_MARKERS[i]).toLowerCase()]) return true;
    }
    return false;
  }

  // entries: [{name, path, size, mtimeMs, hasData}] for the current tick.
  // hasData is false only when the filesystem reports the file occupies no
  // blocks — a dataless cloud placeholder, which reports its full logical size
  // while holding none of the bytes. Undefined means the platform can't tell
  // (Windows), and is treated as real data.
  // prev: {path: {size, stable}} recorded last tick. seen(key) -> bool is the
  // persisted dedupe membership. Ready = candidate, not seen, non-zero size,
  // real data on disk, no in-progress sibling, and a size that has held steady
  // across STABLE_TICKS observations. `sizes` covers every unseen candidate so
  // a failed import stays eligible next tick.
  function planTick(entries, prev, seen) {
    var ready = [];
    var sizes = {};
    var byName = {};
    var i, e;
    for (i = 0; i < entries.length; i++) byName[String(entries[i].name).toLowerCase()] = 1;
    for (i = 0; i < entries.length; i++) {
      e = entries[i];
      if (!isCandidateName(e.name)) continue;
      if (seen(dedupeKey(e.path, e.size, e.mtimeMs))) continue;

      var settled = e.size > 0 &&
        e.hasData !== false &&
        !partnerInProgress(e.name, byName) &&
        prevSize(prev[e.path]) === e.size;

      var stable = settled ? prevStable(prev[e.path]) + 1 : 0;
      sizes[e.path] = { size: e.size, stable: stable };
      if (stable >= STABLE_TICKS) ready.push(e);
    }
    return { ready: ready, sizes: sizes };
  }

  function pruneKeys(keys, max) {
    return keys.length > max ? keys.slice(keys.length - max) : keys;
  }

  var api = {
    isCandidateName: isCandidateName,
    dedupeKey: dedupeKey,
    planTick: planTick,
    STABLE_TICKS: STABLE_TICKS,
    pruneKeys: pruneKeys,
  };

  // CEP's --mixed-context injects Node's `module` into the page, so this
  // must be if/if, not if/else — the panel needs root.FGWatch regardless.
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.FGWatch = api;
})(this);
