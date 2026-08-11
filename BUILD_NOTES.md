# BUILD_NOTES — FootageGrab

Handoff notes: what was built, why it's shaped this way, what was verified
live, and where it can break. v0.1/v0.2 notes first, v0.3 at the end.

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
- **Quality model (revised after first field test)**: v0.1 capped "Best" at
  the best H.264 (= 1080p on YouTube, since 4K+ is VP9/AV1 only) and the user
  immediately hit it on a 4K video. Now **Max** (`-S res,vcodec:h264,acodec:m4a`)
  takes the true highest resolution, and `compat.py` probes the result with
  ffprobe: anything non-H.264 is re-encoded to high-bitrate H.264
  (`h264_videotoolbox` hardware encoder, libx264 fallback, 50 Mbps at 2160p,
  `yuv420p` so 10-bit HDR sources land 8-bit) with ffmpeg `-progress`
  parsing feeding the "Converting for Premiere" UI stage. Transcode failure
  keeps the original file rather than failing the job. 1080p/720p tiers stay
  H.264-native and never transcode. Legacy config value "best" → "max".
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
8. **Real 4K segment, Max quality** (v0.2 quality model): Big Buck Bunny
   0:30–0:35 → downloaded as VP9 2160p60, hardware-transcoded → **3840×2160
   @ 60 fps, H.264 High, AAC, 5.01s, 33 MB**; both `downloading` and
   `transcoding` stages reached the progress UI. Test count now 46.
9. **Premiere MCP bridge on this machine**: `verify_premiere_connection`
   returned ready (CEP backend, open project + active sequence detected) —
   the stopgap import path below is confirmed working.

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

- ~~v1.5 — Premiere auto-import~~ → **shipped in v0.3** as the CEP Bridge
  panel (below). The MCP stopgap is retired — the user rejected any
  AI-in-the-loop import.
- **v2**: session/project profiles, history search + re-download, metadata
  sidecar JSON, ClipDeck `footage`-source deep-links, denser keyboard-first
  mode (yt_clipper-style) if it stays learnable, trim UI for non-YouTube
  sites (v0.4+), invisible auto-start CEP extension so the panel needn't be
  open.
- Windows support (paths + manifest registry locations differ; host logic is
  already platform-guarded).

---

# v0.3 — Premiere auto-import (CEP Bridge) + one-click multi-site grabs

Built 2026-08-11 against HANDOFF-v0.3.md. User decisions locked at session
start: single `FootageGrab` bin · adapters for X/Reddit/TikTok **+ Instagram**
· ~2s quick-dismiss toasts for one-click grabs · nothing to copy from
SmartGrab beyond the speed.

## Architecture added

```
premiere/                       CEP panel "FootageGrab Bridge" (PPRO 23–99)
  CSXS/manifest.xml             --enable-nodejs --mixed-context, CSXS 9.0
  index.html + css/panel.css    popup design language, Premiere-dark bg
  js/watchcore.js               PURE watcher logic (node --test'able)
  js/panel.js                   2s poll loop, config re-read, dedupe, JSX calls
  js/CSInterface.js             Adobe v9.4.0, vendored from DropComp
  jsx/import.jsx                ensureBin + batched importFiles, hand-rolled JSON
install/install-premiere.sh     copy (or --link) + PlayerDebugMode 10/11/12
extension/content/sites/        resolve.js (pure) · core.js (button engine)
                                x.js · reddit.js · tiktok.js · instagram.js
host/footagegrab/prefetch.py    --print metadata prefetch · site tokens · hints
```

## Decisions and why (v0.3)

- **Poll `readdir` every 2s; `fs.watch` only accelerates.** The user's
  projects live on external volumes where FSEvents is unreliable; polling one
  directory at 2s is free. The panel re-reads the extension's `config.json`
  every tick, so changing the folder in the popup retargets the panel with no
  UI coupling.
- **Readiness gate = known video extension, no `.part/.ytdl/.h264tmp` marker,
  non-zero size stable across two consecutive ticks.** The host renames
  transcodes into place atomically, but manual Finder drops are not.
- **Dedupe is two-layered and failure-safe**: a localStorage set of
  `path|size|mtime` keys (mtime in the key so a re-download re-imports after
  the user deletes the project item), plus an ExtendScript walk comparing
  `getMediaPath()` against the live project. Keys are recorded **only after
  JSX reports success**, so a mid-write import attempt can't poison dedupe.
- **`require` vs `cep_node.require`**: with `--mixed-context` Node merges
  into the page — DropComp (proven daily on this machine) uses bare
  `require`. The panel tries bare `require` first, `cep_node` as fallback.
- **JSX returns hand-rolled JSON strings** — ExtendScript's native JSON
  support varies by host version and the payloads are flat; a polyfill would
  be more code than the emitter.
- **Prefetch lives in the worker, not the enqueue handler.** Enqueue must
  answer the extension within its 15s timeout; `yt-dlp --print` (~2–8s, 20s
  cap) runs as the job's first stage ("fetching info") instead. Prefetch
  failure never fails a job — naming falls back to `{site}_{date}`.
- **`{site}` = lowercased extractor key** when prefetch runs, hostname-derived
  otherwise (`x.com → twitter`, `youtu.be → youtube`, `v.redd.it → reddit`).
  New default full template `{title}_{site}_{id}` — stored configs keep their
  old template until edited (config.load only honors stored keys).
- **Adapters are expendable by contract**: ≤80 lines each, selectors
  documented at the top of each file, generic surfaces (context menu, `⌥G`,
  popup row) as the permanent fallback. Buttons mount on the container's
  *parent* because custom elements (`shreddit-player`) and `<video>` don't
  render light-DOM children.
- **Injected ack toast** (`chrome.scripting.executeScript`) for context-menu
  and shortcut grabs — works on pages with no content script at all.

## Verified live (2026-08-11, macOS 26.5, yt-dlp 2026.07.04, Premiere Pro 2026)

1. **68/68 host tests** (`python3 -m unittest discover -s host/tests`) — 46
   existing + 22 new (prefetch parse/site/hints/subprocess incl. timeout, and
   runner integration: prefetch fills job, skip-when-present, failure-safe,
   `{site}` + `site_date` naming).
2. **28/28 node tests** — watchcore readiness/dedupe/prune (11), adapter
   permalink resolvers with captured href fixtures (14), time (3). All JS
   passes `node --check`; both manifests parse.
3. **X full chain, real network**: bare URL enqueued exactly like a
   context-menu grab (no title/id) → prefetch stage fired → download →
   `SpaceX_-_Liftoff!_twitter_2084909824358096896.mp4`, h264 1280×720 —
   **4.2s URL-to-file**, no transcode needed (X serves H.264, as expected).
4. **Error surfacing**: a no-video tweet returns yt-dlp's verbatim
   `No video could be found in this tweet`; login-walled errors get the
   "Enable Browser cookies" hint appended (unit-tested).
5. **Impersonation**: Homebrew yt-dlp shipped **without** curl_cffi (spec
   assumed bundled — false on this machine); installed `curl_cffi==0.13.0`
   into its venv (0.16 is rejected by yt-dlp 2026.07.04). Chrome-133/136
   targets now available.
6. **Panel installed** to `~/Library/Application Support/Adobe/CEP/extensions/
   FootageGrabBridge`; PlayerDebugMode already set (CSXS 11/12) + written for
   10; Premiere 2026 present and CEP-healthy (MCP bridge answered ready).

Not verified live yet (needs a Premiere restart + the panel docked once):
drop-file→bin ≤2s, catch-up scan, external-volume watch. TikTok/Instagram
live grabs untestable from this network (TikTok geo-blocked in India;
Instagram login-walled — cookies path exists). Reddit video grab not
exercised (WAF throttled URL discovery, extractor itself verified resolving
post URLs); the code path is identical to the verified X chain.

## Known risks & limitations (v0.3)

- **Adapter DOM churn**: X/TikTok/Instagram redesign constantly. Selectors
  are one-place-per-file; context menu + `⌥G` are the permanent fallback.
- **Panel only watches while open** — accepted; catch-up covers gaps.
- **TikTok from India needs a VPN** — network-level, not code.
- **`<all_urls>` host permission** — required for grab-anywhere; private
  unpacked extension, documented in README.
- **curl_cffi pin** — `brew upgrade yt-dlp` may drop or outgrow the venv's
  curl_cffi; re-pin `curl_cffi==0.13.0` (or whatever the new yt-dlp accepts)
  if impersonation targets vanish.

## Dev quickstart

```bash
python3 -m unittest discover -s host/tests -v
node --test extension/tests/time.test.js extension/tests/resolve.test.js \
  premiere/tests/watchcore.test.js
python3 host/selftest.py                 # health
python3 host/selftest.py --roundtrip     # spawn host, speak the protocol
./install/install.sh                     # (re)install host + self-test
./install/install-premiere.sh            # (re)install CEP panel (--link: dev)
```

No build step anywhere: `extension/` and `premiere/` load as-is; the host
runs on stock python3. Files stay under 400 lines by design (CSInterface.js
is vendored and exempt).
