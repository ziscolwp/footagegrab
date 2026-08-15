# HANDOFF — FootageGrab v0.3: one-click multi-site grab + true Premiere auto-import

You are continuing an existing, working, live-verified product. **Read
`README.md` and `BUILD_NOTES.md` first**, then this file. Do not re-architect
what already works — v0.3 is two additive features on top of v0.2.

---

## Current state (verified 2026-08-11)

Repo: `/Users/ziscol/Ziscol Media Projects/Youtube AUTOMATION/Footagegrabber`
(git, 2 commits). Working and field-tested by the user on their machine:

- MV3 extension (vanilla JS, no build step) — In/Out markers on YouTube's
  progress bar, pill overlay, hotkeys (I/O/G), toasts, queue/settings popup.
  Extension ID pinned via manifest `key`: `lklbfpaopllmcbehfahbapehpadmlnel`.
- Python native messaging host (`com.footagegrab.host`, stdlib only) — yt-dlp
  + ffmpeg runner, 2-worker job queue, history, installer registered with
  Chrome/Brave/Chromium/Edge/Arc on this Mac.
- Quality model: `max` downloads true highest res; `compat.py` transcodes
  VP9/AV1 → H.264 via `h264_videotoolbox` (verified live: 4K60 → 3840×2160
  H.264 High). 46 tests green (`python3 -m unittest discover -s host/tests`).

### Why v0.3 exists (user's own words, paraphrased)

1. The Premiere-MCP "stopgap import" is **rejected** — it requires asking an
   AI session to run an import. The user wants footage to appear in the
   Premiere **Project panel automatically**, robustly, with no one in the loop.
2. The user wants to grab footage from **X, Reddit, TikTok "and everything"**,
   one click in the browser → download → auto-import. They own a tool called
   **SmartGrab** that does this outside the browser; v0.3 brings that
   experience into the browser. Speed is the product: click → file → bin.

---

## Locked decisions (do not relitigate)

1. **Premiere import = a CEP panel with a watch folder.** Not MCP, not manual.
   CEP (not UXP) because: the user already side-loads a CEP extension daily
   (their **DropComp** AE extension at
   `/Users/ziscol/Ziscol Media Projects/dropcomp` — crib its manifest +
   install pattern), PlayerDebugMode is already proven on this machine, CEP
   has Node for filesystem watching, and `app.project.importFiles` is mature.
   Move to UXP only if their Premiere version has actually removed CEP.
2. **Multi-site = yt-dlp does all extraction.** The host barely changes; the
   extension grows small per-site adapters + generic surfaces. No per-site
   scraping logic of our own, ever.
3. YouTube marker flow stays exactly as is. Non-YouTube sites are **full-video
   grab only** in v0.3 (their clips are short); a trim UI for them is v0.4+.
4. Same repo, same conventions: host stays Python-stdlib-only, extension
   stays no-build vanilla JS, files < 400 lines, tests for all non-trivial
   logic, conventional commits, update `BUILD_NOTES.md` with a verification
   record when done.
5. Still single-user, fully local, no cloud, no accounts. Legal stance
   unchanged (user is responsible for rights; no DRM circumvention).

---

## Part A — Premiere auto-import: CEP panel "FootageGrab Bridge"

### Behavior

Panel docked in Premiere (Window → Extensions → FootageGrab Bridge). While
open, any new video file that lands in the footage folder is imported into a
bin within ~2 seconds — including files the user drops there manually. No
dialogs, no focus stealing, undo-friendly (one import per file).

### Architecture

```
premiere/                        # new top-level folder in this repo
├── CSXS/manifest.xml            # com.footagegrab.bridge, PPro host [23.0,99.9]
├── index.html + js/panel.js     # watcher + UI (CEP browser side, Node enabled)
├── jsx/import.jsx               # ExtendScript: ensureBin, importFiles, findByPath
└── .debug                       # remote debugging port for dev
install/install-premiere.sh      # copies to ~/Library/Application Support/Adobe/CEP/extensions/
                                 # + defaults write com.adobe.CSXS.{10,11,12} PlayerDebugMode 1
```

### Watcher design (the robust part — this is why MCP lost)

- **Source of truth for the folder**: read the selected destination from
  `destinations` / `destination_id` in
  `~/Library/Application Support/FootageGrab/config.json` via CEP Node
  (`window.cep_node.require('fs')`) — `output_dir` no longer exists. Re-read
  it every poll tick so changing the destination in the extension popup
  retargets the panel automatically. Allow a manual override field in the
  panel for edge cases.
- **Poll `readdir` every 2s as the primary mechanism, `fs.watch` only as an
  accelerant.** Critical real-world constraint: the user's projects live on
  an external volume (`/Volumes/Editing_Project/...` — seen live), and the
  footage folder may too; FSEvents is unreliable on external/network volumes.
  Polling a single directory at 2s is free.
- **File-readiness gate**: only import a file when (a) extension is one of
  `.mp4 .mov .mkv .webm .m4v`, (b) name contains no `.part` / `.ytdl` /
  `.h264tmp`, and (c) size is non-zero and unchanged across two consecutive
  ticks. (The host renames transcodes into place atomically, but manual drops
  and Finder copies are not atomic.)
- **Dedupe, two layers**: a persisted set of `path|size|mtime` keys in panel
  localStorage, AND an ExtendScript check that no project item already has
  that media path (walk `app.project.rootItem` recursively comparing
  `getMediaPath()`). Re-importing after the user deletes an item from the
  project should work — that's why mtime/size is in the key, not path alone.
- **Catch-up scan**: on panel open, scan the folder and import anything not
  yet in the project (respecting dedupe). This covers "downloaded while
  Premiere was closed" with zero extra machinery.
- **Pause toggle** in the panel, and a "Import existing now" button that
  forces the catch-up scan.

### ExtendScript side (`jsx/import.jsx`)

```javascript
// signature that matters:
app.project.importFiles([paths], true /*suppressUI*/, targetBin, false /*numberedStills*/);
```
- `ensureBin(name)`: walk `app.project.rootItem.children` for a bin with the
  configured name (default `"FootageGrab"`); create with
  `app.project.rootItem.createBin(name)` if absent. Bin name is a panel
  setting. Import into that bin only — never into the root, never onto a
  sequence.
- Return JSON strings from every JSX function (CSInterface.evalScript only
  passes strings); include ok/error so the panel can toast failures.
- Batch: if several files become ready in one tick, import them in a single
  `importFiles` call (one undo step).

### Panel UI (small, Premiere-native)

Match Premiere's dark slate; reuse FootageGrab's design language (green/amber
accents, monospace paths — see `extension/popup/popup.css` tokens). Contents:
status line (Watching · folder path), bin name field, pause toggle, "Import
existing now", last ~10 imports list, subtle error state when the folder is
missing. No wizard, no tabs. It's a utility the user glances at twice a day.

### Traps (learned or known)

- PlayerDebugMode: write for `com.adobe.CSXS.10`, `.11`, and `.12` — Premiere
  versions differ; extra keys are harmless. User may need to restart Premiere
  AND `killall cfprefsd` for it to take.
- The panel only runs while open. That is **accepted** for v0.3 (editors dock
  it once per workspace and forget it — the catch-up scan covers gaps). An
  invisible auto-start extension (`<AutoVisible>false</AutoVisible>` +
  startup event) is a stretch goal, not required.
- `--enable-nodejs` must be in the manifest's CEFCommandLine or `cep_node` is
  undefined.
- Node in CEP is old (varies by CEP runtime) — write ES2018-ish JS, no
  optional chaining in the panel code until you've verified the runtime.
- Test import of a file that's still being written must NOT poison dedupe
  (only record a key after JSX reports success).

---

## Part B — one-click multi-site grab (X, Reddit, TikTok, …)

### What the user experiences

On a tweet with video / a TikTok / a Reddit post: **one FootageGrab button
(or right-click → "Grab video with FootageGrab", or ⌥G)** → toast "queued" →
file in footage folder → (Part A) appears in the Premiere bin. Zero dialogs.

### Extension changes

1. **Generic surfaces (build these first — they cover "everything")**:
   - `chrome.contextMenus`: "Grab video with FootageGrab" on `page`, `link`,
     and `video` contexts. Link context uses the link URL (right-click a
     tweet timestamp / Reddit post title); page context uses the tab URL.
   - Toolbar popup: a "Grab this page" row at the top of the Queue tab,
     enabled on any http(s) page, showing the tab's hostname.
   - `chrome.commands` shortcut (suggest ⌥G / MacCtrl not conflicting) →
     grab current tab URL.
   - These need `host_permissions` beyond YouTube: request `<all_urls>`
     or per-site lists — `<all_urls>` is fine for a private unpacked
     extension; note it in README.
2. **Site adapters (the SmartGrab feel — small, isolated, expendable)**:
   - `extension/content/sites/<site>.js`, one per site, sharing a tiny core
     (`sites/core.js`): `{ matches, findVideoContainers(root), resolveUrl(container) }`.
     Core mounts a small FG button overlay on each container, wired to
     enqueue full-mode.
   - **X/Twitter**: per-video button; resolve the *tweet permalink* (nearest
     `article` → `a[href*="/status/"]` with time element), never the timeline
     URL. Works on x.com and twitter.com.
   - **TikTok**: button on the active video; URL from `location.href` on
     `/video/` pages and from the item's link in feed view.
   - **Reddit**: button on `shreddit-player` / video posts; resolve the post
     permalink (v.redd.it needs the *post* URL for audio muxing — yt-dlp
     handles it from the comments URL).
   - Adapters are expected to break with site redesigns. Keep each under ~80
     lines, and the generic surfaces always work as fallback. Document each
     adapter's selectors at the top of its file (same convention as `SEL` in
     `content/main.js`).
3. YouTube content script untouched. Toasts: reuse the existing toast system
   on adapter sites (mount to `document.body`, fixed position, since there's
   no player chrome to anchor to — the toasts module already supports a
   container; generalize `mount()`).

### Host changes (small)

1. **Metadata prefetch** when `title`/`video_id` are missing from an enqueue
   (always the case for context-menu grabs):
   `yt-dlp --no-playlist --print "%(title)s\x1f%(id)s\x1f%(extractor_key)s" URL`
   with a ~20s timeout (`--print` implies simulate). Feed results into the
   existing naming pipeline. On prefetch failure, fall back to
   `{site}_{date}` naming — never fail the job over a missing title.
2. **`{site}` template token** (lowercased extractor key: `twitter`,
   `tiktok`, `reddit`, `youtube`) available in filename templates; consider
   defaulting the full-video template to `{title}_{site}_{id}`.
3. Job payload: accept `source: "context_menu" | "adapter" | "toolbar"` for
   history/debugging. Validation: keep URL http(s) check; drop the YouTube
   assumptions (video_id length cap already generous).
4. Per-site notes to encode:
   - Instagram and some X/NSFW-Reddit content require
     `--cookies-from-browser` — setting already exists; surface a clearer
     error hint when yt-dlp says login is required ("Enable browser cookies
     in Settings").
   - Some sites work better with impersonation; if yt-dlp reports a
     curl_cffi/impersonation error, surface it verbatim (Homebrew yt-dlp
     bundles curl_cffi as of 2025 — verify with `yt-dlp --list-impersonate-targets`).
   - TikTok: yt-dlp fetches no-watermark when available — nothing to do,
     but verify in the live test.
   - `-S vcodec:h264` sort is harmless on sites that only serve single-file
     H.264 (X/TikTok/Reddit) — no special-casing needed. `compat.py` already
     rescues any VP9/AV1 outliers.

---

## Suggested build order

1. **Part A first** (it multiplies the value of every grab):
   panel skeleton → JSX import round-trip proven with a hand-dropped file →
   watcher + readiness gate + dedupe → catch-up scan → installer + docs.
2. Part B generic surfaces (context menu, toolbar, command) + host metadata
   prefetch + `{site}` token — this alone delivers "everything" via yt-dlp.
3. Site adapters: X → Reddit → TikTok (in that order of user value).
4. Live verification + BUILD_NOTES + commits (one per part).

## Verification protocol (do it live, like v0.1/v0.2 — see BUILD_NOTES style)

- Unit: watcher readiness/dedupe logic (extract into pure JS testable with
  `node --test`), adapter URL resolvers (feed saved DOM fixtures), metadata
  prefetch parsing, `{site}` templating (host unittest).
- Live: (1) drop a file into the footage folder with the panel open → in bin
  ≤2s; (2) grab while Premiere closed → open Premiere → catch-up imports it;
  (3) context-menu grab of an X video URL and a Reddit post → files named
  sanely; (4) full chain on one URL: click → download → transcode (if any) →
  auto-import, stopwatch the click-to-bin time and record it.
- Rights-safe live test sources: the user's own posts if available, else
  Blender/official promo posts; keep clips seconds long. Ask the user for a
  couple of real target URLs they'd actually grab — they use this daily.

## Definition of done

- [ ] Panel installed via `install/install-premiere.sh`, visible in
      Window → Extensions, watching the configured footage folder
- [ ] New download appears in the configured bin ≤2s after file completion,
      no dialogs, correct dedupe on re-runs
- [ ] Catch-up scan imports files downloaded while Premiere was closed
- [ ] Works with footage folder on an external volume (test on
      `/Volumes/Editing_Project/...`)
- [ ] Context menu + toolbar + shortcut grab works on arbitrary yt-dlp
      supported URLs; X/Reddit/TikTok have in-page buttons
- [ ] Non-YouTube grabs get real titles via prefetch; `{site}` token works
- [ ] YouTube marker flow and all 46 existing tests still green, new logic
      tested, BUILD_NOTES verification record updated
- [ ] README: multi-site usage, Premiere panel install, permissions note

## Open questions — ask the user at session start (don't guess)

1. Bin layout: single `FootageGrab` bin, per-day bins (`FG 2026-08-12`), or
   per-site bins?
2. SmartGrab: anything about its UX worth copying exactly? (Ask for a
   screenshot or a 30s description.)
3. Which sites beyond X/Reddit/TikTok actually matter to them (Instagram?
   Twitch clips? Vimeo?) — adapters are cheap but finite.
4. Should full-video grabs from feeds auto-dismiss their toasts faster, given
   the expected volume?

## References

- `gitttsarya/media-fetcher-premiere` — CEP download→import proof (import
  path is the useful part; our flow is inverted)
- `Adobe-CEP/CEP-Resources` — manifest schema, CSInterface.js, PlayerDebugMode
- Local: `/Users/ziscol/Ziscol Media Projects/dropcomp` — the user's own AE
  CEP extension; copy its install/sideload approach
- yt-dlp supported sites: `yt-dlp --list-extractors` (thousands; trust it)
- This repo's `BUILD_NOTES.md` — architecture rationale + verification style
  expected for v0.3's write-up
