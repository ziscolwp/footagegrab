# FootageGrab

Mark In/Out on any YouTube video and the clip lands in your Premiere footage
folder while you keep hunting the next one. No terminal, no hand-typed yt-dlp
commands.

**The loop:** watch → press `I` at the good part → `O` where it ends → `G` →
keep browsing. By the time you're back in Premiere, the file is in the folder.

- Chrome MV3 extension draws Premiere-style In/Out brackets on YouTube's own
  progress bar; a native messaging host (Python, zero pip dependencies) runs
  yt-dlp + ffmpeg and owns the queue, filenames, and your footage folder.
- Single-user, fully local. No cloud, no accounts, no tracking.
- macOS first. YouTube only (v1).

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

## Settings

| Setting | Notes |
|---|---|
| Footage folder | Where files land. Native folder picker (the popup closes while it's open — reopen to confirm). |
| Quality | **Max (4K+)** grabs the highest resolution the video has. YouTube ships 4K+ only as VP9/AV1, so those are auto-converted (below). 1080p / 720p stick to native H.264 — fastest, never converted. |
| Premiere-safe H.264 | ON (default): VP9/AV1 downloads are converted to high-bitrate H.264 (50 Mbps at 4K) with the Mac's hardware encoder — a 4K clip converts in seconds on Apple Silicon. OFF: keep the original codec. |
| Accurate cut | ON: re-encodes at the cuts so In/Out are frame-trustworthy. OFF: stream copy — starts/ends snap to keyframes (± a few seconds, fine for rough B-roll). |
| Browser cookies | For age/member-restricted videos. macOS will prompt for keychain access. |
| Filename templates | Clips: `{title}_{start}-{end}_{id}` → `Oprah_Interview_00.42-01.18_dQw4w9WgXcQ.mp4`. Tokens: `{title}` `{id}` `{start}` `{end}` `{date}` `{quality}`. Collisions get `_2`, `_3`, … |

Config lives at `~/Library/Application Support/FootageGrab/config.json`;
download history at `history.jsonl` next to it.

## Premiere workflow (v1)

Import from the footage folder as usual (`⌘I` or drag the folder into the
Project panel — Premiere creates a bin from the folder name). Recommended
layout: one footage folder per package/session, e.g.
`.../Oprah Package/Footage/`, switched in FootageGrab settings when you start
a session. A UXP panel that auto-imports new files into a bin is the planned
v1.5 (see BUILD_NOTES).

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Host not reachable" in popup | Run `./install/install.sh`, then **fully quit** (⌘Q) and reopen the browser. |
| Self-test fails | `python3 host/selftest.py` prints tool/folder health; logs at `~/Library/Application Support/FootageGrab/logs/host.log`. |
| Downloads suddenly failing | YouTube changed something — update yt-dlp (button in Settings, or `brew upgrade yt-dlp`). This is routine; yt-dlp ships fixes within days. |
| "Sign in to confirm you're not a bot" / age-restricted | Enable browser cookies in Settings. |
| Markers/pill missing on a video page | YouTube redesigns its player DOM occasionally — selectors live in one place: `extension/content/main.js` (`SEL`). |
| Files land but cuts are a few seconds long | That's fast mode. Turn on **Accurate cut**. |

## Development

```bash
python3 -m unittest discover -s host/tests -v   # 34 tests: logic + host e2e
node --test extension/tests/time.test.js        # extension time formatting
python3 scripts/make_icons.py                   # regenerate icons
```

Layout: `extension/` (MV3, vanilla JS, no build step) · `host/` (Python
stdlib only) · `install/` (installer + native messaging manifest template).
Architecture, verification record, and known risks: [BUILD_NOTES.md](BUILD_NOTES.md).
