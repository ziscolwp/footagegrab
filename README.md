# FootageGrab

Mark In/Out on any YouTube video — or one-click grab from X, Reddit, TikTok,
Instagram, and anything else yt-dlp speaks — and the clip lands in your
Premiere footage folder while you keep hunting the next one. With the
FootageGrab Bridge panel open in Premiere, it lands **in your project's bin**
automatically. No terminal, no hand-typed yt-dlp commands, no manual imports.

**The loop:** watch → press `I` at the good part → `O` where it ends → `G` →
keep browsing. By the time you're back in Premiere, the file is in the bin.
On any other site: right-click → **Grab video with FootageGrab** (or `⌥G`).

- Chrome MV3 extension draws Premiere-style In/Out brackets on YouTube's own
  progress bar; a native messaging host (Python, zero pip dependencies) runs
  yt-dlp + ffmpeg and owns the queue, filenames, and your footage folder.
- A CEP panel ("FootageGrab Bridge") watches the footage folder from inside
  Premiere and auto-imports new files into a bin within ~2 seconds.
- Single-user, fully local. No cloud, no accounts, no tracking.
- macOS first.

> **Legal:** you are responsible for having the rights to any footage you
> download. Personal offline production use only — this tool has no
> redistribution features and does not touch DRM.

## Install (macOS)

1. **Dependencies** (once):

   ```bash
   brew install yt-dlp ffmpeg
   ```

2. **Native host** — from this folder:

   ```bash
   ./install/install.sh
   ```

   This registers the host with every Chromium browser it finds (Chrome,
   Brave, Chromium, Edge, Arc) and runs a self-test. Re-run it any time — for
   example after moving this folder.

3. **Extension**:
   - Open `chrome://extensions`, enable **Developer mode**
   - **Load unpacked** → select the `extension/` folder
   - The ID will be `lklbfpaopllmcbehfahbapehpadmlnel` (pinned by the manifest
     key, so the host trusts it automatically)

4. **Fully restart the browser** (⌘Q — a normal window close is not enough for
   Chrome to pick up native host registrations).

5. Click the FootageGrab toolbar icon → **Settings** → **Choose folder…** and
   point it at your Premiere project's footage folder.

6. **Premiere panel** (optional but recommended):

   ```bash
   ./install/install-premiere.sh
   ```

   Restart Premiere, then open **Window → Extensions → FootageGrab Bridge**
   and dock it anywhere. While it's open, every new file in the footage
   folder is imported into a `FootageGrab` bin automatically.

> **Permissions note:** since v0.3 the extension requests `<all_urls>` host
> access so the context menu / `⌥G` / site buttons work everywhere. It is a
> private unpacked extension — nothing leaves your machine. After pulling an
> update, hit **Reload** on `chrome://extensions`.

## Use

On any YouTube watch page:

| Key | Action |
|---|---|
| `I` | Set In at the playhead |
| `O` | Set Out at the playhead |
| `G` | Grab the marked clip(s) |
| `Shift+G` | Grab the full video |
| `[` / `]` | Nudge In by ±0.25 s (`Shift` nudges Out) |
| `Esc` | Clear the current pair |

- Markers appear as green `[` / amber `]` brackets on the progress bar with a
  gradient band between them. Drag a bracket to adjust it.
- Press `I` again after completing a pair to stage another segment from the
  same video — `G` grabs them all as independent downloads.
- Toasts in the player corner show queued / progress / saved / failed, with
  **Reveal** (Finder) and **Retry** actions. The toolbar badge counts active
  downloads. Keep browsing — downloads run in the host, not the tab.
- The pill (top-right of the player) does everything the keys do, plus `?` for
  the shortcut cheat sheet.

*FootageGrab intentionally overrides YouTube's `i` (miniplayer) shortcut on
watch pages.*

## One-click grabs from X, Reddit, TikTok, Instagram — and everywhere else

Non-YouTube grabs are **full-video** (their clips are short); yt-dlp does all
the extraction, so anything on [its supported-sites list](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) works. Three ways in,
pick whichever is closest to your cursor:

| Surface | Where it works | How |
|---|---|---|
| **Right-click → Grab video with FootageGrab** | any page, link, or video | right-click a tweet's timestamp / a Reddit post title to grab that post; right-click the page background to grab the current URL |
| **`⌥G`** | any page | grabs the current tab's URL (rebind at `chrome://extensions/shortcuts`) |
| **Toolbar popup → Grab this page** | any page | top of the Queue tab, shows the site it will grab |
| **Hover `FG ↓` button** | X, Reddit, TikTok, Instagram | appears on each video; resolves the *post's* permalink even in feeds |

Titles are fetched automatically before download (`yt-dlp --print`), so files
are named sanely — e.g. `SpaceX_-_Liftoff!_twitter_2084909824358096896.mp4`.
If a title can't be fetched, the file falls back to `site_date` naming and
downloads anyway.

- **Instagram** (and NSFW Reddit / some X content) needs **Browser cookies**
  enabled in Settings — the error toast will tell you when.
- **TikTok is geo-blocked in India** — grabs time out without a VPN. The
  button and context menu work; the network is the blocker.
- The in-page buttons are per-site adapters and will break when sites
  redesign; the context menu and `⌥G` always work regardless.

## Settings

| Setting | Notes |
|---|---|
| Footage folder | Where files land. Native folder picker (the popup closes while it's open — reopen to confirm). |
| Quality | **Max (4K+)** grabs the highest resolution the video has. YouTube ships 4K+ only as VP9/AV1, so those are auto-converted (below). 1080p / 720p stick to native H.264 — fastest, never converted. |
| Premiere-safe H.264 | ON (default): VP9/AV1 downloads are converted to high-bitrate H.264 (50 Mbps at 4K) with the Mac's hardware encoder — a 4K clip converts in seconds on Apple Silicon. OFF: keep the original codec. |
| Accurate cut | ON: re-encodes at the cuts so In/Out are frame-trustworthy. OFF: stream copy — starts/ends snap to keyframes (± a few seconds, fine for rough B-roll). |
| Browser cookies | For age/member-restricted videos. macOS will prompt for keychain access. |
| Filename templates | Clips: `{title}_{start}-{end}_{id}` → `Oprah_Interview_00.42-01.18_dQw4w9WgXcQ.mp4`. Tokens: `{title}` `{id}` `{site}` `{start}` `{end}` `{date}` `{quality}`. Collisions get `_2`, `_3`, … `{site}` is the lowercased extractor (`youtube`, `twitter`, `reddit`, `tiktok`); the v0.3 default full-video template is `{title}_{site}_{id}` (configs saved before v0.3 keep their stored template — update it in Settings if you want `{site}`). |

Config lives at `~/Library/Application Support/FootageGrab/config.json`;
download history at `history.jsonl` next to it.

## Premiere workflow — the Bridge panel

Dock **Window → Extensions → FootageGrab Bridge** once per workspace and
forget it. While the panel is open:

- Any new video file in the footage folder (grabbed *or* dropped in by hand)
  is imported into the **FootageGrab** bin within ~2 seconds — no dialogs, no
  focus stealing, one undo step per batch.
- The panel follows the folder set in the extension popup automatically
  (re-read every poll), or you can pin a different folder in its override
  field. Bin name is editable. External volumes
  (`/Volumes/...`) are fine — the watcher polls rather than trusting FSEvents.
- **Catch-up:** anything downloaded while Premiere was closed is imported on
  panel open (or press *Import existing now*). Already-imported files are
  skipped — re-downloading a file re-imports it, deleting a project item and
  pressing *Import existing now* re-imports that too.
- **Pause** stops importing without closing the panel.

The panel only watches while open — that's by design; the catch-up scan
covers the gaps. Files still land in the folder either way.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Host not reachable" in popup | Run `./install/install.sh`, then **fully quit** (⌘Q) and reopen the browser. |
| Self-test fails | `python3 host/selftest.py` prints tool/folder health; logs at `~/Library/Application Support/FootageGrab/logs/host.log`. |
| Downloads suddenly failing | YouTube changed something — update yt-dlp (button in Settings, or `brew upgrade yt-dlp`). This is routine; yt-dlp ships fixes within days. |
| "Sign in to confirm you're not a bot" / age-restricted | Enable browser cookies in Settings. |
| Markers/pill missing on a video page | YouTube redesigns its player DOM occasionally — selectors live in one place: `extension/content/main.js` (`SEL`). |
| `FG ↓` buttons missing on X/Reddit/TikTok/Instagram | Site redesign — each adapter's selectors are documented at the top of its file in `extension/content/sites/`. Right-click → Grab still works meanwhile. |
| Bridge panel not in Window → Extensions | Re-run `./install/install-premiere.sh`, fully restart Premiere. If it still hides, `killall cfprefsd` and restart Premiere again (PlayerDebugMode needs to stick). |
| Panel shows "Folder missing" | The footage folder in the extension settings doesn't exist (unmounted volume?) — fix it in the popup or use the panel's override field. |
| "requires authentication" / login errors on grabs | Enable **Browser cookies** in Settings, retry from the popup. |
| TikTok grabs time out | TikTok is unreachable from India without a VPN. With one, also make sure impersonation is available: `yt-dlp --list-impersonate-targets`. |
| Files land but cuts are a few seconds long | That's fast mode. Turn on **Accurate cut**. |

## Development

```bash
python3 -m unittest discover -s host/tests -v   # 68 tests: logic + host e2e
node --test extension/tests/time.test.js extension/tests/resolve.test.js \
  premiere/tests/watchcore.test.js              # 28 tests: pure JS logic
python3 scripts/make_icons.py                   # regenerate icons
./install/install-premiere.sh --link            # dev: symlink the CEP panel
```

Layout: `extension/` (MV3, vanilla JS, no build step) · `host/` (Python
stdlib only) · `premiere/` (CEP panel: watcher + ExtendScript import) ·
`install/` (installers + native messaging manifest template).
Architecture, verification record, and known risks: [BUILD_NOTES.md](BUILD_NOTES.md).
