// FootageGrab Bridge panel: polls the footage folder every 2s (fs.watch is
// only an accelerant — FSEvents is unreliable on external volumes), gates
// files on readiness, dedupes, and imports batches via jsx/import.jsx.
// ES2018-conservative on purpose: CEP's browser/Node runtimes are dated.
(function () {
  "use strict";

  var TICK_MS = 2000;
  var MAX_KEYS = 500;
  var MAX_RECENT = 10;

  var cs = new CSInterface();
  var fs = null;
  var os = null;
  try {
    // --mixed-context merges Node into the page (bare require, like DropComp);
    // without it Node lives behind the cep_node namespace.
    var nodeRequire = typeof require === "function" ? require
      : typeof cep_node !== "undefined" ? cep_node.require : null;
    if (nodeRequire) {
      fs = nodeRequire("fs");
      os = nodeRequire("os");
    }
  } catch (e) { /* surfaced below as a fatal error */ }

  var $ = function (id) { return document.getElementById(id); };
  var ui = {
    dot: $("dot"), dotLabel: $("dot-label"),
    verb: $("status-verb"), path: $("status-path"), error: $("status-error"),
    hint: $("status-hint"),
    bin: $("bin-name"), dir: $("dir-override"),
    insert: $("insert-toggle"),
    pause: $("pause-btn"), scan: $("scan-btn"), recent: $("recent"),
  };

  // ---- persisted state --------------------------------------------------

  function loadJSON(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) { return fallback; }
  }
  function saveJSON(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {}
  }

  var settings = loadJSON("fg_settings", {});
  var binName = settings.bin || "FootageGrab";
  var dirOverride = settings.dir || "";
  var paused = !!settings.paused;
  var insertToTimeline = settings.insert !== false; // default ON
  // Rotation offset for per-clip color labels; the jsx side mods it into its
  // palette, so this only needs to keep counting (capped to stay small).
  var labelCounter = Number(settings.labelIdx) || 0;

  var seenList = loadJSON("fg_seen_keys", []);
  var seenSet = {};
  for (var i = 0; i < seenList.length; i++) seenSet[seenList[i]] = true;
  function seenHas(key) { return seenSet[key] === true; }
  function seenAdd(key) {
    if (seenSet[key]) return;
    seenSet[key] = true;
    seenList.push(key);
    seenList = FGWatch.pruneKeys(seenList, MAX_KEYS);
    saveJSON("fg_seen_keys", seenList);
  }

  function saveSettings() {
    saveJSON("fg_settings", {
      bin: binName, dir: dirOverride, paused: paused,
      insert: insertToTimeline, labelIdx: labelCounter,
    });
  }

  // ---- folder resolution ------------------------------------------------

  var IS_WIN = typeof process !== "undefined" && process.platform === "win32";
  var APP_HOME = IS_WIN
    ? ((typeof process !== "undefined" && process.env.APPDATA) ||
       (os ? os.homedir() + "/AppData/Roaming" : "~")) + "/FootageGrab"
    : (os ? os.homedir() : "~") + "/Library/Application Support/FootageGrab";
  var CONFIG_PATH = APP_HOME + "/config.json";
  var DEFAULT_DIR = IS_WIN ? "~/Videos/FootageGrab" : "~/Movies/FootageGrab";

  function expandTilde(p) {
    if (p && p.indexOf("~") === 0 && os) return os.homedir() + p.slice(1);
    return p;
  }

  // ---- project path tracking ---------------------------------------------
  // Kept for a future per-project feature; resolveDir() no longer reads it —
  // the extension's selected destination is the single source of truth now.

  var projectPath = ""; // latest app.project.path reported by Premiere

  // Async by nature (evalScript); the cached value feeds the next tick —
  // same eventual-consistency the folder override already relies on.
  function refreshProjectPath() {
    cs.evalScript("FG_projectPath()", function (result) {
      var res = null;
      try { res = JSON.parse(result); } catch (e) {}
      // evalScript fails routinely while Premiere shows a modal (e.g. mid
      // project switch) — only a parsed ok answer may change the cache, so
      // errors keep the last known-good project instead of flapping to "".
      if (!res || res.ok !== true) return;
      var p = String(res.path || "");
      if (p !== projectPath) {
        projectPath = p;
        scheduleSoon();
      }
    });
  }

  // The extension owns the destination now; the panel follows it. A manual
  // override still wins, for the odd case where you want to watch elsewhere.
  function resolveDir() {
    if (dirOverride) return expandTilde(dirOverride);
    try {
      var cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
      var list = (cfg && cfg.destinations) || [];
      for (var i = 0; i < list.length; i++) {
        if (list[i] && list[i].id === cfg.destination_id) return expandTilde(list[i].path);
      }
      if (list.length && list[0].path) return expandTilde(list[0].path);
    } catch (e) { /* no config yet — fall through */ }
    return expandTilde(DEFAULT_DIR);
  }

  // ---- watcher ----------------------------------------------------------

  var sizes = {};        // path -> size from last tick (readiness gate)
  var watchedDir = null; // dir currently polled + fs.watch'ed
  var watcher = null;
  var importing = false;
  var lastError = "";
  var lastHint = "";
  var recent = [];       // [{name, tag, time}]
  var failCounts = {};   // path -> failed import attempts this session
  var MAX_ATTEMPTS = 3;

  function listEntries(dir) {
    var names = fs.readdirSync(dir);
    var entries = [];
    for (var i = 0; i < names.length; i++) {
      var full = dir + "/" + names[i];
      try {
        var st = fs.statSync(full);
        if (st.isFile()) {
          // A dataless cloud placeholder (Dropbox/iCloud online-only) reports
          // its full logical size while occupying zero blocks. Importing one
          // hands Premiere a file with no frames in it. Windows doesn't report
          // blocks, so undefined means "can't tell" and counts as real data.
          var hasData = typeof st.blocks === "number" ? st.blocks > 0 : true;
          entries.push({ name: names[i], path: full, size: st.size, mtimeMs: st.mtimeMs, hasData: hasData });
        }
      } catch (e) { /* vanished mid-listing */ }
    }
    return entries;
  }

  function retarget(dir) {
    watchedDir = dir;
    sizes = {};
    if (watcher) { try { watcher.close(); } catch (e) {} watcher = null; }
    try {
      watcher = fs.watch(dir, function () { scheduleSoon(); });
    } catch (e) { /* polling covers it */ }
  }

  var soonTimer = null;
  function scheduleSoon() {
    if (soonTimer) return;
    soonTimer = setTimeout(function () { soonTimer = null; tick(); }, 300);
  }

  function tick() {
    if (!fs) { setStatus("down", "Node unavailable", "", "CEP Node is disabled — reinstall the panel"); return; }
    refreshProjectPath();
    var dir = resolveDir();
    if (dir !== watchedDir) retarget(dir);
    if (!fs.existsSync(dir)) {
      setStatus("down", "Folder missing", dir, lastError);
      return;
    }
    var entries;
    try {
      entries = listEntries(dir);
    } catch (e) {
      setStatus("down", "Folder unreadable", dir, String(e));
      return;
    }
    var plan = FGWatch.planTick(entries, sizes, seenHas);
    sizes = plan.sizes;
    if (paused) {
      setStatus("warn", "Paused", dir, "");
      return;
    }
    setStatus("ok", "Watching", dir, lastError);
    if (plan.ready.length && !importing) importBatch(plan.ready);
  }

  // ---- import via ExtendScript ------------------------------------------

  function jsxString(s) {
    return '"' + String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"')
      .replace(/\n/g, "\\n").replace(/\r/g, "\\r") + '"';
  }

  function importBatch(readyEntries) {
    importing = true;
    var literals = [];
    for (var i = 0; i < readyEntries.length; i++) literals.push(jsxString(readyEntries[i].path));
    var script = "FG_importBatch([" + literals.join(",") + "]," + jsxString(binName) +
      "," + labelCounter + ")";
    cs.evalScript(script, function (result) {
      // insertImported takes ownership of `importing`; if we never hand off
      // (error, or a throw anywhere here), release it so the watcher can't
      // wedge in a permanent green-but-dead state.
      var handedOff = false;
      try {
        var res = null;
        try { res = JSON.parse(result); } catch (e) {}
        if (!res || !res.ok) {
          // keys stay unrecorded so the batch retries next tick
          lastError = res && res.error ? res.error : "Premiere did not answer (is a project open?)";
          renderStatusError();
          return;
        }
        lastError = "";
        if (res.imported && res.imported.length) {
          // skipped duplicates don't burn a color — only real imports advance
          labelCounter = (labelCounter + res.imported.length) % 10000;
          saveSettings();
        }
        recordOutcome(readyEntries, res.imported || [], "imported");
        recordOutcome(readyEntries, res.skipped || [], "already in project");
        recordFailures(readyEntries, res.failed || []);
        renderRecent();
        renderStatusError();
        insertImported(readyEntries, res.imported || []);
        handedOff = true;
      } finally {
        if (!handedOff) importing = false;
      }
    });
  }

  // Timeline insert runs after the bin import settles so an insert problem
  // can never lose footage — worst case the clip only lands in the bin.
  // `importing` stays true until the insert answers so a batch from the next
  // tick can't interleave its clips mid-chain.
  function insertImported(entries, paths) {
    if (!insertToTimeline || !paths.length) { importing = false; return; }
    var literals = [];
    for (var i = 0; i < paths.length; i++) literals.push(jsxString(paths[i]));
    cs.evalScript("FG_insertAtPlayhead([" + literals.join(",") + "])", function (result) {
      importing = false;
      var res = null;
      try { res = JSON.parse(result); } catch (e) {}
      lastHint = "";
      if (!res || !res.ok) {
        lastError = res && res.error ? res.error : "Imported, but timeline insert failed";
      } else if (res.noSequence) {
        lastHint = "Imported to bin — open a sequence to insert at the playhead";
      } else if (res.failed && res.failed.length) {
        lastError = res.failed.length + " clip(s) imported but could not be inserted";
      }
      retagRecent(entries, (res && res.inserted) || [], "inserted");
      renderRecent();
      renderStatusError();
    });
  }

  // Upgrade the freshly-recorded "imported" rows to "inserted" once the
  // timeline confirms them.
  function retagRecent(entries, paths, tag) {
    for (var i = 0; i < paths.length; i++) {
      for (var j = 0; j < entries.length; j++) {
        if (entries[j].path !== paths[i]) continue;
        for (var k = 0; k < recent.length; k++) {
          if (recent[k].name === entries[j].name && recent[k].tag === "imported") {
            recent[k].tag = tag;
            break;
          }
        }
      }
    }
  }

  // A file Premiere can't import retries a couple of ticks (it may still be
  // settling), then gets a dedupe key so it stops poisoning every scan.
  function recordFailures(entries, paths) {
    for (var i = 0; i < paths.length; i++) {
      failCounts[paths[i]] = (failCounts[paths[i]] || 0) + 1;
      if (failCounts[paths[i]] < MAX_ATTEMPTS) continue;
      for (var j = 0; j < entries.length; j++) {
        if (entries[j].path === paths[i]) {
          seenAdd(FGWatch.dedupeKey(entries[j].path, entries[j].size, entries[j].mtimeMs));
          recent.unshift({ name: entries[j].name, tag: "failed", time: new Date() });
        }
      }
    }
    if (paths.length) {
      lastError = paths.length + " file(s) Premiere couldn't import (unsupported format?)";
    }
    if (recent.length > MAX_RECENT) recent.length = MAX_RECENT;
  }

  function recordOutcome(entries, paths, tag) {
    for (var i = 0; i < paths.length; i++) {
      for (var j = 0; j < entries.length; j++) {
        if (entries[j].path === paths[i]) {
          seenAdd(FGWatch.dedupeKey(entries[j].path, entries[j].size, entries[j].mtimeMs));
          recent.unshift({ name: entries[j].name, tag: tag, time: new Date() });
        }
      }
    }
    if (recent.length > MAX_RECENT) recent.length = MAX_RECENT;
  }

  // ---- UI ---------------------------------------------------------------

  function setStatus(kind, verb, path, error) {
    ui.dot.className = "dot " + kind;
    ui.dotLabel.textContent = kind === "ok" ? "live" : kind === "warn" ? "paused" : "error";
    ui.verb.textContent = verb;
    ui.path.textContent = path;
    lastError = error || "";
    renderStatusError();
  }

  function renderStatusError() {
    ui.error.hidden = !lastError;
    ui.error.textContent = lastError;
    ui.hint.hidden = !lastHint;
    ui.hint.textContent = lastHint;
  }

  function fmtTime(d) {
    var h = d.getHours(), m = d.getMinutes();
    return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
  }

  function renderRecent() {
    ui.recent.innerHTML = "";
    if (!recent.length) {
      var empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Nothing imported yet";
      ui.recent.appendChild(empty);
      return;
    }
    for (var i = 0; i < recent.length; i++) {
      var row = document.createElement("div");
      row.className = "import-row";
      var name = document.createElement("span");
      name.className = "import-name";
      name.textContent = recent[i].name;
      name.title = recent[i].name;
      var tag = document.createElement("span");
      tag.className = "import-tag" +
        (recent[i].tag === "imported" || recent[i].tag === "inserted" ? ""
          : recent[i].tag === "failed" ? " fail" : " dup");
      tag.textContent = recent[i].tag;
      var time = document.createElement("span");
      time.className = "import-time";
      time.textContent = fmtTime(recent[i].time);
      row.appendChild(name); row.appendChild(tag); row.appendChild(time);
      ui.recent.appendChild(row);
    }
  }

  function renderPause() {
    ui.pause.textContent = paused ? "Resume" : "Pause";
    ui.pause.className = "btn btn-ghost" + (paused ? " paused" : "");
  }

  // ---- wiring -----------------------------------------------------------

  ui.bin.value = binName;
  ui.dir.value = dirOverride;
  ui.insert.checked = insertToTimeline;
  renderPause();

  ui.insert.addEventListener("change", function () {
    insertToTimeline = ui.insert.checked;
    if (!insertToTimeline) { lastHint = ""; renderStatusError(); }
    saveSettings();
  });

  ui.bin.addEventListener("change", function () {
    binName = ui.bin.value.trim() || "FootageGrab";
    ui.bin.value = binName;
    saveSettings();
  });
  ui.dir.addEventListener("change", function () {
    dirOverride = ui.dir.value.trim();
    saveSettings();
    tick();
  });
  ui.pause.addEventListener("click", function () {
    paused = !paused;
    saveSettings();
    renderPause();
    tick();
  });
  // Catch-up on demand: two quick ticks so pre-existing files pass the
  // size-stable-across-two-ticks gate immediately.
  ui.scan.addEventListener("click", function () {
    tick();
    setTimeout(tick, 600);
  });

  tick(); // first tick doubles as the catch-up scan on panel open
  setInterval(tick, TICK_MS);
})();
