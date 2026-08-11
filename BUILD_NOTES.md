# BUILD_NOTES — FootageGrab v0.1.0

Handoff notes: what was built, why it's shaped this way, what was verified
live, and where it can break.

## Architecture

```
extension/ (MV3, vanilla JS, no build step)
  content/   markers on the progress bar, pill overlay, toasts, hotkeys
  background/service-worker.js — owns the native port, req/resp matching,
             relays job pushes to tabs + popup, badge = active job count
  popup/     Queue tab (live + history) · Settings tab (host config)
        │ chrome native messaging (framed JSON over stdio)
        ▼
host/ (Python 3, stdlib only — nothing to pip install)
  footagegrab/nm.py        framing          timefmt.py  time parse/format
  footagegrab/naming.py    slug/template/collisions
  footagegrab/sections.py  yt-dlp argv construction (pure, tested)
  footagegrab/jobs.py      state machine + threaded queue (2 workers)
  footagegrab/runner.py    subprocess yt-dlp, progress parse, cleanup, cancel
  footagegrab/router.py    message dispatch    system.py  Finder/picker/health
  footagegrab_host.py      entry: logging, history, drain-on-disconnect
  selftest.py              health report + native messaging roundtrip
install/   install.sh (browsers: Chrome/Brave/Chromium/Edge/Arc) + uninstall.sh
```

### Decisions and why

- **Native messaging over a localhost daemon.** No port, no auth token, no
  launchd unit; Chrome's `allowed_origins` is the auth. The extension's ID is
  **pinned by a `key` in manifest.json** (ID `lklbfpaopllmcbehfahbapehpadmlnel`
  on every machine), so the host manifest works without a per-install ID dance.
  Trade-off: a full browser quit can kill the host mid-download (see risks).
- **H.264+AAC preferred over max resolution** (`-S vcodec:h264,res,acodec:m4a`).
  Premiere doesn't read VP9/AV1 without plugins; an editor tool should never
  deliver a file Premiere rejects. Consequence: "Best" typically = 1080p.
- **Accurate cut = yt-dlp `--force-keyframes-at-cuts`** (re-encode at cuts),
  not a hand-rolled pad+ffmpeg-trim pipeline. The pad approach can't know the
  actual keyframe offset of the padded download without probing
  (YoutubeSegmentDownloader's core lesson), while force-keyframes is yt-dlp's
  supported answer to exactly this. Verified frame-exact below.
- **Chrome's PATH problem**: GUI-launched Chrome doesn't have `/opt/homebrew/bin`.
  The host prepends Homebrew/MacPorts paths and config can override tool paths.
- **Host is the source of truth** for config, queue, history (survives browser
  restarts in `~/Library/Application Support/FootageGrab/`). The extension
  keeps only a session mirror for the badge/popup.
- **Native folder picker via `osascript choose folder`** run by the host — a
  real folder dialog with no extra permissions. Chrome closes the popup when
  the dialog takes focus; the host still saves the choice (hinted in UI).
- **Hotkeys use `e.code` in a capture-phase listener** and intentionally
  override YouTube's `i` (miniplayer). Esc is only consumed when a draft pair
  exists, so fullscreen-exit still works.

## Verified live (2026-08-11, macOS 26.5, yt-dlp 2026.07.04, ffmpeg 8.0.1)

1. **34/34 host tests green** (`python3 -m unittest discover -s host/tests`),
   including an e2e test that spawns the real host process, speaks framed
   native messaging, enqueues 2 segments against a stubbed yt-dlp, sees both
   reach `done` with distinct collision-free filenames, rejects an invalid
   segment with a human message, and reads history back from disk.
2. **3/3 extension time tests** (`node --test extension/tests/time.test.js`);
   all JS passes `node --check`; manifest parses.
3. **Real segment, fast mode**: Big Buck Bunny 0:10–0:15 →
   `Big_Buck_Bunny_00.10-00.15_aqz-KE-bpKQ.mp4`, 5.03s, h264/aac.
4. **Real segment, accurate mode**: 0:20–0:24 → exactly 4.00s, h264/aac.
5. **Real full download**: "Me at the zoo" → 18.95s file; title
   `Me at the zoo: "test"/\|?*` sanitized to `Me_at_the_zoo_test_…`; progress
   parsing fired 11 callbacks up to 100%.
6. **Error surfacing**: unavailable video → clean `This video is unavailable`
   reached the job error field (no stack traces).
7. **Installer on this machine**: registered with Chrome, Brave, Chromium,
   Edge, Arc; native messaging roundtrip through the installed launcher OK.

Not yet exercised by an automated test: the content-script UI against live
YouTube DOM (markers, pill, toasts) — manual-verify on first run; selectors
are centralized for quick repair (below).

## Known risks & limitations

- **YouTube DOM churn**: every selector lives in `SEL` at the top of
  `extension/content/main.js`. If markers/pill vanish after a YouTube
  redesign, fix that one map.
- **yt-dlp breakage cadence**: YouTube changes break yt-dlp routinely.
  Settings has an "Update yt-dlp" button; Homebrew installs are detected and
  told to `brew upgrade yt-dlp`. Errors surface verbatim in toasts/popup.
- **Segment progress is indeterminate**: yt-dlp hands sections to its ffmpeg
  downloader, which emits no `%` lines. The UI shows an indeterminate bar for
  segments (full downloads show real percentages).
- **Browser quit mid-download**: on disconnect the host drains in-flight jobs
  (up to 1h) before exiting, but Chrome may SIGKILL sooner on a full quit.
  yt-dlp's `.part` files mean no corrupt finals; failed jobs can be retried.
- **Fast-mode cut drift** scales with the video's keyframe interval — close on
  the test video, can be seconds on long-GOP uploads. Accurate mode is exact.
- **Ads / live streams**: marking is blocked during ads (marks would land on
  ad time) and on live streams (no finite duration).
- **Multi-pair drag** on staged (non-draft) pairs shares one handle style;
  staged pairs render dimmer but are equally draggable — by design.

## Deferred (agreed scope)

- **v1.5 — Premiere auto-import**: UXP panel with a watch folder + "Import new
  into bin". Note: this machine already has a Premiere MCP with
  `import_folder` — a stopgap is asking Claude to import the footage folder
  into a bin until the panel exists.
- **v2**: session/project profiles, history search + re-download, metadata
  sidecar JSON, ClipDeck `footage`-source deep-links, denser keyboard-first
  mode (yt_clipper-style) if it stays learnable.
- Windows support (paths + manifest registry locations differ; host logic is
  already platform-guarded).

## Dev quickstart

```bash
python3 -m unittest discover -s host/tests -v
node --test extension/tests/time.test.js
python3 host/selftest.py                 # health
python3 host/selftest.py --roundtrip     # spawn host, speak the protocol
./install/install.sh                     # (re)install + self-test
```

No build step anywhere: `extension/` loads unpacked as-is; the host runs on
stock python3. Files stay under 400 lines by design.
