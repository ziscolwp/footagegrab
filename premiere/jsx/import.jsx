// FootageGrab Bridge — ExtendScript side. Every function returns a JSON
// string (CSInterface.evalScript only passes strings). JSON is emitted by
// hand: ExtendScript's JSON support varies by host version, and our shapes
// are flat enough not to need a polyfill.

function FG__q(s) {
  s = String(s);
  var out = '"';
  for (var i = 0; i < s.length; i++) {
    var c = s.charAt(i);
    var code = s.charCodeAt(i);
    if (c === '"') out += '\\"';
    else if (c === "\\") out += "\\\\";
    else if (code < 32) out += "\\u" + ("000" + code.toString(16)).slice(-4);
    else out += c;
  }
  return out + '"';
}

function FG__arr(list) {
  var parts = [];
  for (var i = 0; i < list.length; i++) parts.push(FG__q(list[i]));
  return "[" + parts.join(",") + "]";
}

function FG__err(message) {
  return '{"ok":false,"error":' + FG__q(message) + "}";
}

function FG__binType() {
  return typeof ProjectItemType !== "undefined" ? ProjectItemType.BIN : 2;
}

// Canonical form for path comparison: panel paths use forward slashes even on
// Windows, while getMediaPath() returns native backslashes.
function FG__norm(p) {
  return String(p).toLowerCase().replace(/\\/g, "/");
}

// Recursively collect lowercase media paths of every clip in the project.
function FG__collectPaths(item, out) {
  var kids = item.children;
  if (!kids) return;
  for (var i = 0; i < kids.numItems; i++) {
    var child = kids[i];
    if (child.type === FG__binType()) {
      FG__collectPaths(child, out);
    } else {
      try {
        var p = child.getMediaPath();
        if (p) out[FG__norm(p)] = true;
      } catch (e) {} // sequences etc. have no media path
    }
  }
}

function FG__ensureBin(name) {
  var root = app.project.rootItem;
  var kids = root.children;
  for (var i = 0; i < kids.numItems; i++) {
    var child = kids[i];
    if (child.type === FG__binType() &&
        String(child.name).toLowerCase() === String(name).toLowerCase()) {
      return child;
    }
  }
  var made = root.createBin(name);
  if (made) return made;
  // some Premiere versions return undefined from createBin — re-walk
  kids = root.children;
  for (var j = 0; j < kids.numItems; j++) {
    var again = kids[j];
    if (again.type === FG__binType() && String(again.name) === String(name)) return again;
  }
  return null;
}

// The saved project file's path, or "" for unsaved projects — the panel
// derives the project-relative footage folder from it.
function FG_projectPath() {
  try {
    if (!app.project) return '{"ok":true,"path":""}';
    var p = "";
    try { p = String(app.project.path || ""); } catch (e) {}
    return '{"ok":true,"path":' + FG__q(p) + "}";
  } catch (e) {
    return FG__err("projectPath failed: " + e.toString());
  }
}

function FG_ping() {
  try {
    if (!app.project) return FG__err("no project open");
    return '{"ok":true,"project":' + FG__q(app.project.name) + "}";
  } catch (e) {
    return FG__err("ping failed: " + e.toString());
  }
}

// Recursively find the project item whose media path matches (lowercase).
function FG__findByPath(item, wanted) {
  var kids = item.children;
  if (!kids) return null;
  for (var i = 0; i < kids.numItems; i++) {
    var child = kids[i];
    if (child.type === FG__binType()) {
      var hit = FG__findByPath(child, wanted);
      if (hit) return hit;
    } else {
      try {
        var p = child.getMediaPath();
        if (p && FG__norm(p) === wanted) return child;
      } catch (e) {}
    }
  }
  return null;
}

// After insertClip lands at (or near) `atSeconds`, locate the actual clip on
// the track: same media path, start closest to the requested time. Insert can
// snap to a frame boundary, so exact equality is unreliable.
function FG__findInserted(track, wantedPath, atSeconds) {
  var best = null;
  var bestDelta = 0.5; // more than any frame duration, less than any clip
  for (var i = 0; i < track.clips.numItems; i++) {
    var clip = track.clips[i];
    try {
      var p = clip.projectItem.getMediaPath();
      if (!p || FG__norm(p) !== wantedPath) continue;
    } catch (e) { continue; }
    var delta = Math.abs(clip.start.seconds - atSeconds);
    if (delta < bestDelta) { bestDelta = delta; best = clip; }
  }
  return best;
}

// paths: files already imported by FG_importBatch. Inserts each (in order)
// into V1 of the active sequence at the playhead, chaining back-to-back, then
// parks the playhead at the end of the last inserted clip so the next grab
// continues the sequence. Insert edit (ripple), never overwrite.
function FG_insertAtPlayhead(paths) {
  try {
    if (!app.project) return FG__err("no project open");
    var seq = app.project.activeSequence;
    if (!seq) {
      return '{"ok":true,"noSequence":true,"inserted":[],"failed":' + FG__arr(paths) + "}";
    }
    var track = seq.videoTracks && seq.videoTracks.numTracks > 0 ? seq.videoTracks[0] : null;
    if (!track) return FG__err("active sequence has no video track");
    var at = seq.getPlayerPosition().seconds;
    var inserted = [];
    var failed = [];
    var lastEndTicks = null;
    for (var i = 0; i < paths.length; i++) {
      var wanted = FG__norm(paths[i]);
      var item = FG__findByPath(app.project.rootItem, wanted);
      if (!item) { failed.push(paths[i]); continue; }
      try {
        track.insertClip(item, at);
      } catch (e) { failed.push(paths[i]); continue; }
      var clip = FG__findInserted(track, wanted, at);
      if (!clip) { failed.push(paths[i]); continue; }
      inserted.push(paths[i]);
      at = clip.end.seconds;
      lastEndTicks = clip.end.ticks;
    }
    if (lastEndTicks !== null) {
      try { seq.setPlayerPosition(lastEndTicks); } catch (e) {}
    }
    return '{"ok":true,"noSequence":false,"inserted":' + FG__arr(inserted) +
           ',"failed":' + FG__arr(failed) + "}";
  } catch (e) {
    return FG__err("insert failed: " + e.toString());
  }
}

// Rotation of visually distinct Premiere label indices: Caribbean, Rose,
// Mango, Cerulean, Magenta, Yellow, Purple, Green, Blue, Brown. Near-twins
// (Violet/Iris/Lavender, Forest vs Green) are left out on purpose.
var FG_LABELS = [2, 6, 7, 4, 11, 15, 8, 13, 9, 14];

// Each freshly imported clip gets the next label in the rotation so grabs are
// telling-apart-able at a glance in the bin and on the timeline. labelStart is
// the panel's persisted rotation offset. setColorLabel arrived ~PPro 14; on
// older hosts coloring silently no-ops rather than failing the import.
function FG__labelImported(bin, imported, labelStart) {
  var start = labelStart > 0 ? Math.floor(labelStart) : 0;
  for (var i = 0; i < imported.length; i++) {
    var item = FG__findByPath(bin, FG__norm(imported[i]));
    if (!item) continue;
    try { item.setColorLabel(FG_LABELS[(start + i) % FG_LABELS.length]); } catch (e) {}
  }
}

// paths: JS array literal built by the panel. One importFiles call for the
// whole batch = one undo step. Never imports into the root or a sequence.
function FG_importBatch(paths, binName, labelStart) {
  try {
    if (!app.project) return FG__err("no project open");
    var existing = {};
    FG__collectPaths(app.project.rootItem, existing);
    var toImport = [];
    var skipped = [];
    for (var i = 0; i < paths.length; i++) {
      if (existing[FG__norm(paths[i])]) skipped.push(paths[i]);
      else toImport.push(paths[i]);
    }
    if (toImport.length === 0) {
      return '{"ok":true,"imported":[],"skipped":' + FG__arr(skipped) + "}";
    }
    var bin = FG__ensureBin(binName || "FootageGrab");
    if (!bin) return FG__err("could not create bin: " + binName);
    // batch first (one undo step); if Premiere rejects the batch, fall back
    // to per-file so one unimportable file can't poison the others
    var imported = [];
    var failed = [];
    var ok = false;
    try { ok = app.project.importFiles(toImport, true, bin, false); } catch (eb) { ok = false; }
    if (ok) {
      imported = toImport;
    } else {
      for (var k = 0; k < toImport.length; k++) {
        var one = false;
        try { one = app.project.importFiles([toImport[k]], true, bin, false); } catch (eo) { one = false; }
        if (one) imported.push(toImport[k]);
        else failed.push(toImport[k]);
      }
    }
    FG__labelImported(bin, imported, labelStart);
    return '{"ok":true,"imported":' + FG__arr(imported) +
           ',"skipped":' + FG__arr(skipped) +
           ',"failed":' + FG__arr(failed) + "}";
  } catch (e) {
    return FG__err("import failed: " + e.toString());
  }
}
