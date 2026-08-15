# PO Token Sidecar — Design

**Date:** 2026-08-15
**Status:** Approved for planning. Not implemented.

## Problem

Segment grabs fail with `Requested format is not available`, `HTTP Error 403`,
and `ffmpeg exited with code 8`. Root cause is YouTube's SABR rollout plus
per-video GVS PO tokens: most player clients no longer return playable formats
without a token, and the ones that do are degraded.

## Constraints

- **Segment-only.** In/out points stay exactly as they are. Whole-video
  download-and-cut is out of scope and explicitly rejected.
- **Serial execution.** One grab at a time. No parallel queue, no new UI.
- Must work on macOS and Windows.

## What was measured (2026-08-15, yt-dlp 2026.07.04)

These are test results, not assumptions. Re-verify if YouTube changes.

| Finding | Result |
|---|---|
| `web`, `web_safari`, `tv`, `ios` | Storyboard images only — unusable |
| `android_vr` | Works, no token needed |
| `mweb` without token | Works, but degraded to progressive 360p (format 18) |
| `mweb` **with** POT provider | Full adaptive streams (`243+251`) — **the win** |
| `web_safari` **with** POT provider | Still storyboards only — token does *not* revive SABR-gated clients |
| Cached extraction (`--load-info-json`) | **403s 3/3.** Stream URLs are session-bound. Dead end. |
| Segment grabs, POT vs no POT | 5/5 both ways — no 403 reproduced today, effect on 403s **unmeasured** |
| `--sleep-interval 2 --max-sleep-interval 5` | No measurable cost on single grabs (applies between batch items) |
| `--plugin-dirs` | Silently fails to load plugins ("Plugin directories: none") |
| `~/.config/yt-dlp/plugins/` | Loads correctly — **use this, not `--plugin-dirs`** |

## Rejected alternatives

- **Extraction cache** (one extraction reused across segments of a video).
  Tested and dead: googlevideo URLs are bound to the extraction session and
  403 immediately on reuse. It reproduces the original bug by construction.
- **Full-source prefetch cache.** Violates the segment-only constraint.
- **Adopting an existing tool** (MeTube, Pinchflat, Tube Archivist, ytdl-sub).
  All are whole-video archival tools. None do timestamped segment extraction
  or Premiere integration. Adopting one would be a downgrade.
- **Parallel job queue.** Explicitly not wanted; serial is preferred.

## Design

### Component: POT provider sidecar

The [Rust provider](https://github.com/jim60105/bgutil-ytdlp-pot-provider-rs)
binary, serving HTTP on `127.0.0.1:4416`. Chosen over the Node/Deno original
because it ships a single prebuilt binary per platform with no JS runtime
dependency — significantly simpler for Windows users.

Trade-off accepted: it is an unofficial fork and may lag upstream when YouTube
changes. If it lags, the documented fallback is Brainicism's Node build.

### Component: supervisor (new module in the Python host)

Owns the sidecar's lifecycle. The host already persists across grabs
(`connectNative` in `extension/background/service-worker.js:17`), so it is the
natural owner. Nothing new for the user to launch.

Responsibilities, kept behind a small interface so it can be tested without
spawning real processes:

- `ensure_running()` — start the binary if the port is not answering. Called
  before a grab, not at host startup, so the cost is only paid when grabbing.
- `health_check()` — `GET /ping`, short timeout.
- Restart on death, with a bounded retry count so a broken binary cannot
  spin forever.
- Idle shutdown after a configurable period.
- **Never fail a grab because the sidecar is unavailable.** If it cannot
  start, log it and proceed tokenless — degraded (360p progressive) beats
  broken. This mirrors how `prefetch.py` treats metadata failure.

### Plugin installation

The yt-dlp plugin half installs to the platform plugin directory:

- macOS: `~/.config/yt-dlp/plugins/bgutil-ytdlp-pot-provider/`
- Windows: `%APPDATA%\yt-dlp\plugins\bgutil-ytdlp-pot-provider\`

Handled by the existing installers in `install/`. Do **not** attempt
`--plugin-dirs` — it does not work.

### Changes to `sections.py`

- `FORMAT_SERVING_CLIENTS` becomes the ordered fallback chain
  `("mweb", "android_vr", "tv_downgraded")`.
- `--force-keyframes-at-cuts` stays gated behind the existing `accurate`
  toggle. It forces a re-encode; making it unconditional taxes every grab.

### What does NOT change

The retry ladder stays exactly as it is. A PO token is proven to fix *format
discovery*; its effect on the intermittent 403/exit-8 is unmeasured. The
ladder remains the only thing covering that failure mode. Removing or weakening
it on the assumption that tokens fix 403s would be unsupported by evidence.

## Error handling

| Failure | Behaviour |
|---|---|
| Sidecar binary missing | Log once, proceed tokenless |
| Sidecar won't start / port busy | Bounded retries, then proceed tokenless |
| Sidecar dies mid-session | Restart on next `ensure_running()` |
| Token fetch times out | Proceed tokenless for that grab |
| Grab still 403s | Existing retry ladder handles it |

## Testing

- Supervisor unit tests with a fake process/port — no real binary, no network.
- `sections.py` argv tests extend the existing pure-function pattern in
  `host/tests/test_sections.py`.
- Cross-platform path resolution tested like `test_windows.py` does today.
- Manual verification: confirm `mweb` returns adaptive formats with the
  sidecar up, and progressive-only with it down.

## Open questions

- Idle-shutdown period — needs a real number.
- Whether to pin a specific provider release or track latest.
- Where the binary lives on disk and how it gets updated.
