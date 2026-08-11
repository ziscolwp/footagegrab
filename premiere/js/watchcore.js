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

  // entries: [{name, path, size, mtimeMs}] for the current tick.
  // prevSizes: {path: size} recorded last tick. seen(key) -> bool is the
  // persisted dedupe membership. Ready = candidate, not seen, non-zero size
  // unchanged since last tick. `sizes` covers every unseen candidate so a
  // failed import stays eligible next tick.
  function planTick(entries, prevSizes, seen) {
    var ready = [];
    var sizes = {};
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      if (!isCandidateName(e.name)) continue;
      if (seen(dedupeKey(e.path, e.size, e.mtimeMs))) continue;
      sizes[e.path] = e.size;
      if (e.size > 0 && prevSizes[e.path] === e.size) ready.push(e);
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
    pruneKeys: pruneKeys,
  };

  // CEP's --mixed-context injects Node's `module` into the page, so this
  // must be if/if, not if/else — the panel needs root.FGWatch regardless.
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.FGWatch = api;
})(this);
