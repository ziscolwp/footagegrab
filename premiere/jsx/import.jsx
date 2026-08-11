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
        if (p) out[String(p).toLowerCase()] = true;
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

function FG_ping() {
  try {
    if (!app.project) return FG__err("no project open");
    return '{"ok":true,"project":' + FG__q(app.project.name) + "}";
  } catch (e) {
    return FG__err("ping failed: " + e.toString());
  }
}

// paths: JS array literal built by the panel. One importFiles call for the
// whole batch = one undo step. Never imports into the root or a sequence.
function FG_importBatch(paths, binName) {
  try {
    if (!app.project) return FG__err("no project open");
    var existing = {};
    FG__collectPaths(app.project.rootItem, existing);
    var toImport = [];
    var skipped = [];
    for (var i = 0; i < paths.length; i++) {
      if (existing[String(paths[i]).toLowerCase()]) skipped.push(paths[i]);
      else toImport.push(paths[i]);
    }
    if (toImport.length === 0) {
      return '{"ok":true,"imported":[],"skipped":' + FG__arr(skipped) + "}";
    }
    var bin = FG__ensureBin(binName || "FootageGrab");
    if (!bin) return FG__err("could not create bin: " + binName);
    var ok = app.project.importFiles(toImport, true, bin, false);
    if (!ok) return FG__err("Premiere rejected the import");
    return '{"ok":true,"imported":' + FG__arr(toImport) +
           ',"skipped":' + FG__arr(skipped) + "}";
  } catch (e) {
    return FG__err("import failed: " + e.toString());
  }
}
