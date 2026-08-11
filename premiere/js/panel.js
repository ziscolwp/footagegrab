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
    bin: $("bin-name"), dir: $("dir-override"),
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
    saveJSON("fg_settings", { bin: binName, dir: dirOverride, paused: paused });
  }

  // ---- folder resolution ------------------------------------------------

  var CONFIG_PATH = (os ? os.homedir() : "~") +
    "/Library/Application Support/FootageGrab/config.json";

  function expandTilde(p) {
    if (p && p.indexOf("~") === 0 && os) return os.homedir() + p.slice(1);
    return p;
  }

  // Re-read every tick so changing the folder in the extension popup
  // retargets the panel automatically.
  function resolveDir() {
    if (dirOverride) return expandTilde(dirOverride);
    try {
      var cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
      if (cfg && cfg.output_dir) return expandTilde(String(cfg.output_dir));
    } catch (e) { /* no config yet — fall through */ }
    return expandTilde("~/Movies/FootageGrab");
  }

  // ---- watcher ----------------------------------------------------------

  var sizes = {};        // path -> size from last tick (readiness gate)
  var watchedDir = null; // dir currently polled + fs.watch'ed
  var watcher = null;
  var importing = false;
  var lastError = "";
  var recent = [];       // [{name, tag, time}]

  function listEntries(dir) {
    var names = fs.readdirSync(dir);
    var entries = [];
    for (var i = 0; i < names.length; i++) {
      var full = dir + "/" + names[i];
      try {
        var st = fs.statSync(full);
        if (st.isFile()) {
          entries.push({ name: names[i], path: full, size: st.size, mtimeMs: st.mtimeMs });
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
    var script = "FG_importBatch([" + literals.join(",") + "]," + jsxString(binName) + ")";
    cs.evalScript(script, function (result) {
      importing = false;
      var res = null;
      try { res = JSON.parse(result); } catch (e) {}
      if (!res || !res.ok) {
        // keys stay unrecorded so the batch retries next tick
        lastError = res && res.error ? res.error : "Premiere did not answer (is a project open?)";
        renderStatusError();
        return;
      }
      lastError = "";
      recordOutcome(readyEntries, res.imported || [], "imported");
      recordOutcome(readyEntries, res.skipped || [], "already in project");
      renderRecent();
      renderStatusError();
    });
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
      tag.className = "import-tag" + (recent[i].tag === "imported" ? "" : " dup");
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
  renderPause();

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
