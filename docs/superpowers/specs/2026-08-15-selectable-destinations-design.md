# Selectable Destinations & Atomic Delivery — Design

**Date:** 2026-08-15
**Status:** Approved, not yet implemented. Rollout is staged — see *Rollout*.

## Problem

The host hands yt-dlp the final output path, so downloads are written in place.
When the destination is a Dropbox folder, three failures follow:

1. **Half-written files reach the edit.** An interrupted download leaves
   `<name>.mp4.part` in the destination. Importing one gives Premiere a clip
   whose index promises more frames than exist, and Premiere aborts with
   *"Frame substitution recursion attempt aborting after multiple attempts."*
2. **Partial data syncs.** Dropbox uploads `.part` files as they are written,
   wasting bandwidth and showing collaborators debris from failed attempts.
3. **The destination is not directly choosable.** It is the global `output_dir`,
   silently overridden by the Premiere panel's project claim whenever a project
   is open. Two sources of truth, neither visible at grab time.

A standalone mover script (staging folder + background agent, macOS and Windows)
was built on 2026-08-15 and works, but it treats the symptom: it exists only
because the host writes in place, and it must be installed and maintained on
every machine and both operating systems.

## Constraints

- **macOS and Windows.** Delivery must be atomic on both.
- **Existing installs migrate silently.** No hand-editing of `config.json`.
- **The Premiere panel keeps working** throughout, including its placeholder and
  stability hardening.
- Staged rollout: validated locally before other editors or Windows see it.

## What was measured (2026-08-15)

Test results from this machine, not assumptions.

| Finding | Result |
|---|---|
| Interrupted `.part` file, container index vs real data | Index claims 1557 video frames; **1471 decode**. The 86 missing frames are what Premiere recurses on. |
| Repairing that file by remux (`-c copy`) | Fails — phantom index entries survive |
| Repairing it by trimming to the last good frame | Fails — same gap persists |
| Dropbox online-only file, size vs blocks | Reports **697,415 bytes, 0 blocks on disk** — a stable full size with no data |
| `xattr -w com.dropbox.ignored 1` on a folder inside `~/Library/CloudStorage/Dropbox-*` | Accepted, reads back as `1` |
| Rename from `<dest>/.fg-tmp` into `<dest>` | Succeeds — same volume, atomic |
| Fixed `quality: "1080"` against a 2011 video capped at 720p | `Requested format is not available` — the request names a format the video does not have |

The placeholder measurement is the reason the panel hardening stays: a watcher
that trusts a stable size cannot distinguish a finished download from a file
holding no bytes at all.

## Rejected alternatives

- **Keep the mover script.** Works, but is a second tool to install per machine
  and per OS, solving a problem the host can solve once. Retired by this design.
- **Stage in the system temp folder.** Cross-volume, so delivery degrades to a
  copy — the partial file is visible under its final name for the whole copy.
  Staging must share a volume with the destination for the rename to be atomic.
- **Keep project-follow.** An invisible override is the reason the destination
  is currently hard to reason about. The extension's selection becomes the only
  truth; the panel reads it rather than competing with it.
- **Store the selection in extension storage.** The panel and a second browser
  could not see it. The host config is the shared surface.

## Design

### Component: destinations in config

`output_dir`, `project_output_dir` and `project_output_dir_ts` are replaced by:

```json
"destinations": [
  { "id": "d1", "label": "Chris Tucker — Dropbox", "path": "/Users/…/Videos" },
  { "id": "d2", "label": "Local scratch",          "path": "~/Movies/FootageGrab" }
],
"destination_id": "d1"
```

`id` is opaque and stable. `label` is user-facing and defaults to the folder's
own name. `path` keeps `~` unexpanded, as `output_dir` does today.

**Migration** runs on load: an existing `output_dir` becomes the first entry and
the selection; the project-claim fields are dropped. `effective_output_dir(cfg)`
keeps its name and signature and now resolves the selected destination, so
callers do not change.

### Component: atomic delivery

`runner.py` stops passing the final path to yt-dlp. Per job:

1. Resolve the destination; fail fast if it is missing or unwritable.
2. Ensure `<destination>/.fg-tmp` exists, marked ignored by Dropbox
   (`com.dropbox.ignored` xattr on macOS, the same-named alternate data stream
   on Windows). Best-effort — a failure to mark it is logged, not fatal.
3. Download and post-process entirely inside `.fg-tmp`.
4. `os.replace()` the finished file to its final path.

`os.replace` is atomic within a volume on both platforms. Nothing appears in the
destination under a real name until it is complete, so neither Dropbox nor the
Premiere watcher can observe a partial file.

The existing `.fg-tmp` fallback directory in `_run_fallback` merges into this —
one staging directory per destination, not two.

### Component: host protocol

| Message | Behaviour |
|---|---|
| `get_config` | Returns `destinations` and `destination_id` |
| `set_destination` | `{id}` — selects; error if unknown |
| `add_destination` | Opens the native folder chooser, appends, returns the entry |
| `remove_destination` | `{id}` — removes; if it was selected, falls back to the first remaining |
| `enqueue` | Accepts optional `destination_id` for a one-off override; the selection is unchanged |

The `choose_folder` **message** is superseded by `add_destination` and is
removed from the router. `system.choose_folder()` itself stays — it is the
native folder chooser, and `add_destination` calls it.

### Component: extension UI

A **Save to** dropdown in the popup listing the destinations, the current one
selected, with `Add folder…` as the last item. Selection writes through to the
host, so Chrome and Brave agree and the panel can read it.

### Component: Premiere panel

`syncProjectDir`, `projectFootageDir` and the "Follow project" toggle are
removed, along with `PROJECT_CLAIM_TTL` and the heartbeat. The panel resolves
its watch folder as: manual override if set, otherwise the selected destination
from `config.json`. Setting the destination in the extension therefore moves the
watcher too.

The readiness hardening stays and is **ported into the repo**: it currently
exists only in the installed copy at
`~/Library/Application Support/Adobe/CEP/extensions/FootageGrabBridge`, so a
reinstall from this repo would silently revert it. It requires a file's size to
hold steady across `STABLE_TICKS` observations, refuses any file reporting zero
blocks on disk, and holds back a name whose `.part` sibling still exists.

### What does NOT change

- Segment grabbing, in/out points, naming templates, counters.
- The retry ladder and the POT sidecar.
- The panel's import path and bin handling.

## Rollout

**Phase 1 — local.** Implement, test, and run on ziscol's primary Mac against a
real project. The mover's launch agent is unloaded during this phase but the
files are left on disk until Phase 1 passes.

**Phase 2 — publish.** Only after Phase 1 holds: Windows host verification,
installer updates, then distribution to the other editors. The mover is deleted
in this phase — agent, scheduled task, scripts, and
`~/Ziscol Media Projects/footagegrab-mover/`.

## Error handling

| Situation | Behaviour |
|---|---|
| Destination missing or unwritable | Job fails at enqueue, message names the folder |
| Destination removed while selected | Falls back to the first remaining entry |
| No destinations at all | Host reports "no destination set"; the popup shows `Add folder…` only |
| `.fg-tmp` left by a crash | Swept at host startup |
| `os.replace` fails (permissions, vanished folder) | Job fails, staged file removed, destination untouched |
| Dropbox ignore attribute cannot be set | Logged; delivery still atomic, only the temp folder syncs |

## Testing

- `test_config.py` — migration from an `output_dir`-only config; add, remove,
  select; removing the selected entry; empty list.
- `test_runner.py` — the destination stays empty until the file is complete; a
  failed download leaves the destination empty and no staged file behind;
  `.fg-tmp` is created and swept.
- `premiere/tests/watchcore.test.js` — the ported hardening: placeholder never
  imports, growing file never settles, `.part` sibling holds a name back,
  zero-byte held back, legacy state tolerated, Windows path unaffected.
- Extension tests — destination list rendering and selection.
- Manual, Phase 1 — grab a segment straight to the Dropbox folder and confirm
  via `ls -a` mid-download that no partial file is visible under its final name.

## Open questions

None outstanding. Settled during design on 2026-08-15:

- **Picker shape** — a saved destinations list, not a per-grab folder browser.
- **Project-follow** — dropped entirely rather than kept as a live list entry.
- **Mover** — retired completely rather than kept as a fallback.
