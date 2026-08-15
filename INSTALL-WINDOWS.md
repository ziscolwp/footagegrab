# FootageGrab — Windows Install Runbook

Step-by-step installation for Windows 10/11. Written so an AI agent (Claude,
Copilot, ChatGPT, etc.) can execute it for you top-to-bottom — every step has
a **Verify** block with the expected result — but each step also works as a
plain manual checklist.

> **Note for AI agents:** run steps in order and confirm each Verify block
> before moving on. Steps 5 and 7 involve browser/Premiere UI a human must
> click through — tell your user exactly what to click, then verify. Do not
> continue past a failed Verify; use the Troubleshooting table at the bottom.

**What gets installed** (all current-user, no admin rights needed):

| Component | Where |
|---|---|
| Native host (Python, no pip packages) | runs from this project folder |
| Host registration | `HKCU` registry keys + manifest in `%APPDATA%\FootageGrab` |
| PO token sidecar (auto, best-effort) | `%APPDATA%\FootageGrab\bin\bgutil-pot.exe` |
| Chrome extension (unpacked) | loaded from `extension\` in this folder |
| Premiere panel "FootageGrab Bridge" (optional) | user CEP extensions folder |

---

## 1. Python 3

Install Python 3.9+ and make sure it is on PATH.

```powershell
winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
```

Manual alternative: [python.org/downloads](https://www.python.org/downloads/)
— tick **"Add python.exe to PATH"** in the installer.

**Verify** (open a *new* terminal so PATH refreshes):

```powershell
python --version
```

Expected: `Python 3.x.x` (3.9 or newer). If `python` opens the Microsoft
Store instead, disable the alias under *Settings → Apps → Advanced app
settings → App execution aliases*, or install from python.org.

## 2. yt-dlp and ffmpeg

```powershell
winget install yt-dlp --accept-package-agreements --accept-source-agreements
winget install ffmpeg --accept-package-agreements --accept-source-agreements
```

**Verify** (new terminal again):

```powershell
yt-dlp --version
ffmpeg -version
```

Expected: a date-style version from yt-dlp (e.g. `2026.xx.xx`) and an
`ffmpeg version ...` banner. Both must resolve from PATH.

## 3. Get the project

Pick a **permanent** location — the browser registration points at this
folder, so moving it later means re-running the installer.

```powershell
git clone https://github.com/ziscolwp/footagegrab.git "$env:USERPROFILE\Documents\FootageGrab"
cd "$env:USERPROFILE\Documents\FootageGrab"
```

Manual alternative (no git): green **Code** button on GitHub → **Download
ZIP** → unzip to `Documents\FootageGrab`.

**Verify:**

```powershell
Test-Path .\install\install.ps1
```

Expected: `True`.

## 4. Register the native host

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install\install.ps1
```

Manual alternative: double-click `install\install.bat`.

This registers the host for Chrome, Edge, Brave, and Chromium (current user
only), downloads the PO token sidecar (best-effort — grabs still work
without it, just at lower quality on some videos), and runs a self-test.
Safe to re-run any time.

**Verify:** the script output ends with a passing self-test, and:

```powershell
Test-Path "$env:APPDATA\FootageGrab\com.footagegrab.host.json"
Get-ItemProperty -Path "HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.footagegrab.host" -ErrorAction SilentlyContinue
```

Expected: `True`, and the registry entry's default value points at the
manifest JSON. (Edge/Brave users: check the matching key under their vendor
path instead.)

## 5. Load the extension  *(human-in-the-browser step)*

1. Open `chrome://extensions` (or `edge://extensions`, `brave://extensions`)
2. Enable **Developer mode** (top right)
3. **Load unpacked** → select the `extension` folder inside this project
4. **Fully close and reopen the browser** — every window. A normal window
   close is not enough for Chromium to pick up native host registrations.

**Verify:** the extension card shows ID
`lklbfpaopllmcbehfahbapehpadmlnel` (pinned by the manifest key — the host
only trusts this ID). After the browser restart, click the FootageGrab
toolbar icon: the popup must **not** show "Host not reachable".

## 6. Choose your footage folder

Click the FootageGrab toolbar icon → **Settings** → **Add folder** and pick
the folder your clips should land in (e.g. your Premiere project's footage
folder). You can save several folders and switch between them per grab.

> Cloud-synced folders (Dropbox, OneDrive, Google Drive) are fine as
> destinations: downloads are staged outside the synced folder and moved in
> as one atomic, finished file, so the sync client never sees a partial
> download.

**Verify:** the settings popup lists the folder with no error badge.

## 7. Premiere panel  *(optional but recommended; human step)*

```powershell
.\install\install-premiere.bat
```

Then restart Premiere Pro fully and open **Window → Extensions →
FootageGrab Bridge**. Dock it anywhere. While it is open, every new file in
the footage folder is imported into a `FootageGrab` bin automatically
(and inserted at the playhead if that toggle is on).

**Verify:** the panel appears under Window → Extensions and shows the
watched folder path.

## 8. Acceptance test

1. Open any YouTube video in the browser
2. Press `I` at a start point, `O` a few seconds later, then `G`
3. Watch the toolbar badge — it shows progress

**Expected:** an `.mp4` appears in your chosen folder within seconds of the
badge finishing (name = video title + counter). If the Bridge panel is open
in Premiere, the clip also appears in the `FootageGrab` bin.

---

## Updating

```powershell
cd "$env:USERPROFILE\Documents\FootageGrab"
git pull
powershell -NoProfile -ExecutionPolicy Bypass -File .\install\install.ps1
.\install\install-premiere.bat
```

(ZIP users: re-download and replace the folder, then run the same two
installers.) Reload the extension at `chrome://extensions` (⟳ on the
FootageGrab card) and restart Premiere. Settings are kept — they live in
`%APPDATA%\FootageGrab`, not in the project folder.

## Uninstall

Double-click `install\uninstall.bat` (removes registrations, the sidecar,
and the yt-dlp plugin), remove the extension from `chrome://extensions`,
and delete the project folder.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Popup says "Host not reachable" | Re-run step 4, then **fully** close and reopen the browser (all windows). |
| `python` opens the Microsoft Store | Disable the App execution alias (step 1) or reinstall from python.org with "Add to PATH" ticked. |
| `yt-dlp`/`ffmpeg` not found in step 4's self-test | New terminal after winget; or log out/in so PATH refreshes for GUI-launched processes. |
| Grabs fail with "Sign in to confirm…" | Extension Settings → set **Browser cookies** to your browser. |
| PO token sidecar failed to download | Ignore — grabs work tokenless; re-run step 4 later to retry. |
| H.264 conversion is slow | Expected on non-NVIDIA GPUs (CPU x264 fallback). NVIDIA machines use NVENC automatically. |
| Bridge panel missing in Premiere | Re-run step 7, then fully restart Premiere. |
| Moved the project folder | Re-run step 4 (and step 7 if you use the panel). |

> **Legal reminder:** you are responsible for having the rights to any
> footage you download. Personal offline production use only.
