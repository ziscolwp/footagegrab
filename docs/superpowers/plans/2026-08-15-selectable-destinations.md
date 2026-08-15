# Selectable Destinations & Atomic Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick a download destination from a saved list in the Chrome extension, and make the host deliver finished files into it atomically, so a partial download can never appear in a Dropbox folder or in Premiere.

**Architecture:** `output_dir` and the Premiere panel's project claim collapse into a `destinations` list plus a `destination_id` selection in the host config. The runner stops handing yt-dlp the final path — it downloads into `<destination>/.fg-tmp`, a folder marked ignored by Dropbox, and `os.replace()`s the finished file into place. Same volume, so the move is atomic. The Premiere panel reads the same selection instead of competing with it.

**Tech Stack:** Python 3 (stdlib only, `unittest`), Chrome MV3 extension (ES modules, no framework), Adobe CEP panel (ES5-conservative JS, `node --test`).

**Spec:** `docs/superpowers/specs/2026-08-15-selectable-destinations-design.md`

## Global Constraints

- **Phase 1 only.** This plan stops at local validation on macOS. Windows verification, installer updates, distribution to other editors, and deleting `~/Ziscol Media Projects/footagegrab-mover/` are Phase 2 and are explicitly out of scope.
- **macOS and Windows must both work in code**, even though only macOS is verified in Phase 1. Never use a POSIX-only call without a Windows branch.
- **Python: standard library only.** No new dependencies.
- **Panel JS stays ES5-conservative** — it runs in CEP's embedded browser. No arrow functions, `const`/`let`, or template literals in `premiere/js/*.js`.
- **Existing installs must migrate silently.** A config containing only `output_dir` must keep working with no user action.
- **Branch:** all work lands on `feature/selectable-destinations`, which already exists and holds the spec commit.
- **Commit style:** conventional commits (`feat(host):`, `test(panel):`, `refactor(extension):`).
- **Run tests from the `host/` directory**: `cd host && python3 -m pytest tests/ -q`.

---

### Task 1: Destinations model in config

Replaces `output_dir` / `project_output_dir` / `project_output_dir_ts` with a list and a selection, keeping `effective_output_dir(cfg)` and `ensure_output_dir(cfg)` working so no caller changes yet.

**Files:**
- Modify: `host/footagegrab/config.py:16-37` (DEFAULTS), `:83-93` (load), `:111-154` (update), `:157-179` (claim logic → delete)
- Test: `host/tests/test_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `config.destinations(cfg) -> list[dict]` — each `{"id": str, "label": str, "path": str}`
  - `config.selected_destination(cfg) -> dict | None`
  - `config.add_destination(path: str, label: str = "") -> tuple[dict, dict]` — returns `(cfg, entry)`; selects the new entry
  - `config.remove_destination(dest_id: str) -> tuple[dict, str]` — returns `(cfg, error)`; `error` is `""` on success
  - `config.select_destination(dest_id: str) -> tuple[dict, str]`
  - `config.effective_output_dir(cfg) -> str` — unchanged name/signature, now resolves the selection
  - `config.ensure_output_dir(cfg) -> Path` — unchanged
  - Deleted: `config.PROJECT_CLAIM_TTL`, `config.project_claim_fresh`

- [ ] **Step 1: Write the failing tests**

Add to `host/tests/test_config.py`, and **delete** these now-obsolete tests: `test_project_output_dir_wins_while_claim_is_fresh`, `test_stale_project_claim_falls_back_to_global`, `test_missing_claim_timestamp_falls_back_to_global`, `test_empty_project_output_dir_falls_back`, `test_project_output_dir_survives_load_roundtrip`.

```python
    def test_legacy_output_dir_migrates_to_a_selected_destination(self):
        legacy = str(Path(self.tmp.name) / "old-folder")
        config.save({"output_dir": legacy, "quality": "max"})
        cfg = config.load()
        dests = config.destinations(cfg)
        self.assertEqual(len(dests), 1)
        self.assertEqual(dests[0]["path"], legacy)
        self.assertEqual(dests[0]["label"], "old-folder")
        self.assertEqual(cfg["destination_id"], dests[0]["id"])
        self.assertEqual(config.effective_output_dir(cfg), legacy)

    def test_project_claim_fields_are_dropped_on_migration(self):
        config.save({"output_dir": "~/a", "project_output_dir": "/tmp/claimed",
                     "project_output_dir_ts": 9e9})
        cfg = config.load()
        self.assertNotIn("project_output_dir", cfg)
        self.assertEqual(config.effective_output_dir(cfg), "~/a")

    def test_add_destination_appends_labels_and_selects(self):
        first = str(Path(self.tmp.name) / "one")
        second = str(Path(self.tmp.name) / "two")
        config.add_destination(first)
        cfg, entry = config.add_destination(second, label="Chris Tucker")
        self.assertEqual(entry["label"], "Chris Tucker")
        self.assertEqual(cfg["destination_id"], entry["id"])
        self.assertEqual([d["path"] for d in config.destinations(cfg)],
                         [first, second])

    def test_add_destination_defaults_label_to_folder_name(self):
        cfg, entry = config.add_destination(str(Path(self.tmp.name) / "Videos"))
        self.assertEqual(entry["label"], "Videos")

    def test_ids_are_unique(self):
        config.add_destination(str(Path(self.tmp.name) / "one"))
        cfg, _ = config.add_destination(str(Path(self.tmp.name) / "two"))
        ids = [d["id"] for d in config.destinations(cfg)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_select_destination_switches_the_effective_dir(self):
        cfg, a = config.add_destination(str(Path(self.tmp.name) / "a"))
        cfg, b = config.add_destination(str(Path(self.tmp.name) / "b"))
        cfg, err = config.select_destination(a["id"])
        self.assertEqual(err, "")
        self.assertEqual(config.effective_output_dir(cfg), a["path"])

    def test_select_unknown_destination_reports_an_error(self):
        cfg, err = config.select_destination("nope")
        self.assertNotEqual(err, "")

    def test_removing_the_selected_destination_falls_back_to_the_first(self):
        cfg, a = config.add_destination(str(Path(self.tmp.name) / "a"))
        cfg, b = config.add_destination(str(Path(self.tmp.name) / "b"))
        cfg, err = config.remove_destination(b["id"])
        self.assertEqual(err, "")
        self.assertEqual(cfg["destination_id"], a["id"])

    def test_removing_the_last_destination_leaves_no_selection(self):
        cfg, a = config.add_destination(str(Path(self.tmp.name) / "a"))
        cfg, err = config.remove_destination(a["id"])
        self.assertEqual(config.destinations(cfg), [])
        self.assertIsNone(config.selected_destination(cfg))

    def test_effective_output_dir_falls_back_to_the_default_when_empty(self):
        cfg = config.load()
        self.assertEqual(config.effective_output_dir(cfg),
                         config.DEFAULTS["output_dir"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd host && python3 -m pytest tests/test_config.py -q`
Expected: FAIL with `AttributeError: module 'footagegrab.config' has no attribute 'destinations'`

- [ ] **Step 3: Implement the model**

In `config.py`, replace the three `output_dir` / `project_output_dir` / `project_output_dir_ts` entries in `DEFAULTS` with:

```python
DEFAULTS = {
    # Saved footage folders, chosen from the extension. The legacy single
    # output_dir migrates in as the first entry on load — see _migrate.
    "destinations": [],          # [{"id": str, "label": str, "path": str}]
    "destination_id": "",        # id of the selected entry, "" when none
    "quality": "max",  # max | 1080 | 720  ("best" is a legacy alias for max)
    ...
```

Keep every other key exactly as it is. Add a module-level default path, since `DEFAULTS["output_dir"]` no longer exists:

```python
DEFAULT_DESTINATION = (
    "~/Movies/FootageGrab" if sys.platform == "darwin" else "~/Videos/FootageGrab"
)
```

Then replace the claim block (`PROJECT_CLAIM_TTL` through `effective_output_dir`) with:

```python
def _new_id(existing):
    """Short, stable, collision-free id for a destination entry."""
    n = 1
    taken = {d.get("id") for d in existing}
    while f"d{n}" in taken:
        n += 1
    return f"d{n}"


def _migrate(cfg, stored):
    """Fold a pre-destinations config forward. Mutates and returns cfg."""
    if cfg.get("destinations"):
        return cfg
    legacy = str(stored.get("output_dir") or "").strip()
    if not legacy:
        return cfg
    entry = {"id": "d1", "label": Path(legacy).name or legacy, "path": legacy}
    cfg["destinations"] = [entry]
    cfg["destination_id"] = entry["id"]
    return cfg


def destinations(cfg):
    """The saved folders, as a list of {id, label, path} dicts."""
    raw = cfg.get("destinations")
    if not isinstance(raw, list):
        return []
    return [d for d in raw if isinstance(d, dict) and d.get("id") and d.get("path")]


def selected_destination(cfg):
    """The chosen entry, or None when the list is empty."""
    entries = destinations(cfg)
    if not entries:
        return None
    for entry in entries:
        if entry["id"] == cfg.get("destination_id"):
            return entry
    return entries[0]


def add_destination(path, label=""):
    """Append a folder and select it. Returns (config, entry)."""
    cfg = load()
    path = str(path).strip()
    entries = destinations(cfg)
    entry = {
        "id": _new_id(entries),
        "label": str(label).strip() or Path(path).name or path,
        "path": path,
    }
    entries.append(entry)
    cfg["destinations"] = entries
    cfg["destination_id"] = entry["id"]
    save(cfg)
    return cfg, entry


def remove_destination(dest_id):
    """Drop a folder. Returns (config, error). Selection falls back to first."""
    cfg = load()
    entries = destinations(cfg)
    kept = [d for d in entries if d["id"] != dest_id]
    if len(kept) == len(entries):
        return cfg, f"unknown destination: {dest_id}"
    cfg["destinations"] = kept
    if cfg.get("destination_id") == dest_id:
        cfg["destination_id"] = kept[0]["id"] if kept else ""
    save(cfg)
    return cfg, ""


def select_destination(dest_id):
    """Choose a folder. Returns (config, error)."""
    cfg = load()
    if not any(d["id"] == dest_id for d in destinations(cfg)):
        return cfg, f"unknown destination: {dest_id}"
    cfg["destination_id"] = dest_id
    save(cfg)
    return cfg, ""


def effective_output_dir(cfg):
    """The folder downloads use (unexpanded)."""
    entry = selected_destination(cfg)
    return entry["path"] if entry else DEFAULT_DESTINATION
```

Update `load()` so migration runs and the list survives the `DEFAULTS` whitelist:

```python
def load():
    cfg = dict(DEFAULTS)
    cfg["destinations"] = []
    stored = {}
    try:
        parsed = json.loads(config_path().read_text("utf-8"))
        if isinstance(parsed, dict):
            stored = parsed
            cfg.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, json.JSONDecodeError):
        pass
    if cfg.get("quality") == "best":  # pre-0.2 configs
        cfg["quality"] = "max"
    return _migrate(cfg, stored)
```

In `update()`, delete `"output_dir"` and `"project_output_dir"` from the string-coercion tuple at `:142-151` and delete the `output_dir cannot be empty` check. The list is only edited through the dedicated functions above, never through a generic patch.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd host && python3 -m pytest tests/test_config.py -q`
Expected: PASS

- [ ] **Step 5: Run the whole host suite to catch callers you broke**

Run: `cd host && python3 -m pytest tests/ -q`
Expected: failures only in `test_runner.py` / `test_host_e2e.py` where they set `output_dir` directly. Fix those by calling `config.add_destination(str(tmpdir))` in their setup instead of writing `output_dir`.

- [ ] **Step 6: Commit**

```bash
git add host/footagegrab/config.py host/tests/
git commit -m "feat(host): replace output_dir and project claim with a destinations list"
```

---

### Task 2: Cloud-ignored staging directory

A staging folder inside the destination, marked so Dropbox never uploads its contents.

**Files:**
- Modify: `host/footagegrab/system.py` (add `mark_cloud_ignored`), `host/footagegrab/config.py` (add `ensure_stage_dir`)
- Test: `host/tests/test_config.py`

**Interfaces:**
- Consumes: `config.ensure_output_dir(cfg) -> Path` from Task 1.
- Produces:
  - `system.mark_cloud_ignored(path) -> bool` — best-effort; `True` when the marker was written
  - `config.ensure_stage_dir(out_dir: Path) -> Path` — creates `<out_dir>/.fg-tmp`, marks it, returns it
  - `config.STAGE_DIR_NAME = ".fg-tmp"`

- [ ] **Step 1: Write the failing tests**

```python
    def test_ensure_stage_dir_creates_a_marked_folder_inside_the_destination(self):
        dest = Path(self.tmp.name) / "Videos"
        dest.mkdir()
        stage = config.ensure_stage_dir(dest)
        self.assertEqual(stage, dest / ".fg-tmp")
        self.assertTrue(stage.is_dir())

    def test_ensure_stage_dir_is_idempotent(self):
        dest = Path(self.tmp.name) / "Videos"
        dest.mkdir()
        first = config.ensure_stage_dir(dest)
        second = config.ensure_stage_dir(dest)
        self.assertEqual(first, second)

    def test_stage_dir_shares_a_volume_with_the_destination(self):
        # Atomic delivery depends on this: os.replace across volumes fails.
        dest = Path(self.tmp.name) / "Videos"
        dest.mkdir()
        stage = config.ensure_stage_dir(dest)
        self.assertEqual(os.stat(stage).st_dev, os.stat(dest).st_dev)
```

And in a new `host/tests/test_system.py`:

```python
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab import system


class MarkCloudIgnoredTests(unittest.TestCase):
    def test_marking_a_real_folder_reports_success_on_supported_platforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = system.mark_cloud_ignored(Path(tmp))
            if sys.platform in ("darwin", "win32"):
                self.assertTrue(result)
            else:
                self.assertFalse(result)

    def test_marking_a_missing_path_returns_false_and_does_not_raise(self):
        self.assertFalse(system.mark_cloud_ignored(Path("/no/such/folder/anywhere")))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd host && python3 -m pytest tests/test_system.py tests/test_config.py -q`
Expected: FAIL with `AttributeError: module 'footagegrab.system' has no attribute 'mark_cloud_ignored'`

- [ ] **Step 3: Implement**

In `system.py`:

```python
def mark_cloud_ignored(path):
    """Tell Dropbox to skip this folder. Best effort — returns True if marked.

    macOS uses an extended attribute; Windows the same-named alternate data
    stream. Failure is not fatal: delivery is still atomic, the temp folder
    just syncs.
    """
    path = Path(path)
    if not path.exists():
        return False
    try:
        if sys.platform == "darwin":
            os.setxattr(str(path), "com.dropbox.ignored", b"1")
            return True
        if sys.platform == "win32":
            with open(f"{path}:com.dropbox.ignored", "w", encoding="ascii") as f:
                f.write("1")
            return True
    except OSError:
        return False
    return False
```

Add `import os` to `system.py` if it is not already imported.

In `config.py`:

```python
STAGE_DIR_NAME = ".fg-tmp"


def ensure_stage_dir(out_dir):
    """Staging folder inside the destination, hidden from Dropbox.

    It must live on the destination's volume — delivery is an os.replace, and
    that is only atomic within one filesystem.
    """
    from . import system  # local import: system imports config at module level
    stage = Path(out_dir) / STAGE_DIR_NAME
    stage.mkdir(parents=True, exist_ok=True)
    system.mark_cloud_ignored(stage)
    return stage
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd host && python3 -m pytest tests/test_system.py tests/test_config.py -q`
Expected: PASS

- [ ] **Step 5: Verify the marker really lands on a Dropbox folder**

Run:
```bash
cd host && python3 -c "
from footagegrab import config
from pathlib import Path
d = Path.home() / 'Library/CloudStorage/Dropbox-Ziscolwp/Youtube Videos/Chris Tucker Funny Moments/Videos'
s = config.ensure_stage_dir(d)
import subprocess; print(subprocess.run(['xattr','-p','com.dropbox.ignored',str(s)],capture_output=True,text=True).stdout)
"
```
Expected: prints `1`. Then remove it: `rmdir "$HOME/Library/CloudStorage/Dropbox-Ziscolwp/Youtube Videos/Chris Tucker Funny Moments/Videos/.fg-tmp"`

- [ ] **Step 6: Commit**

```bash
git add host/footagegrab/system.py host/footagegrab/config.py host/tests/
git commit -m "feat(host): add cloud-ignored staging directory helper"
```

---

### Task 3: Atomic delivery in the runner

The change that makes downloading straight to Dropbox safe.

**Files:**
- Modify: `host/footagegrab/runner.py:38-47` (setup), `:129-136` (completion), `:182-241` (`_run_fallback` staging), and add `_deliver` + `sweep_stage_dirs`
- Test: `host/tests/test_runner.py`

**Interfaces:**
- Consumes: `config.ensure_stage_dir(out_dir) -> Path`, `config.ensure_output_dir(cfg) -> Path`, `naming.unique_path(directory, stem, ext) -> Path`.
- Produces:
  - `runner.DownloadRunner._deliver(staged_path: Path, out_dir: Path) -> Path` — moves a finished file into the destination and returns its final path
  - `runner.sweep_stage_dir(out_dir: Path) -> None` — module-level, removes a leftover staging folder

**Note on names:** the class is `DownloadRunner` (imported as `from .runner import DownloadRunner` in `footagegrab_host.py:53`). Existing tests build it as `DownloadRunner(lambda: cfg)` — a positional zero-argument config getter.

- [ ] **Step 1: Write the failing tests**

Add to `host/tests/test_runner.py`:

```python
    def test_deliver_moves_a_staged_file_into_the_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            stage = config.ensure_stage_dir(dest)
            staged = stage / "clip.mp4"
            staged.write_bytes(b"data")
            r = runner.DownloadRunner(lambda: {})
            final = r._deliver(staged, dest)
            self.assertEqual(final, dest / "clip.mp4")
            self.assertTrue(final.is_file())
            self.assertFalse(staged.exists())

    def test_deliver_never_overwrites_an_existing_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            (dest / "clip.mp4").write_bytes(b"original")
            stage = config.ensure_stage_dir(dest)
            staged = stage / "clip.mp4"
            staged.write_bytes(b"new")
            r = runner.DownloadRunner(lambda: {})
            final = r._deliver(staged, dest)
            self.assertEqual(final.name, "clip_2.mp4")
            self.assertEqual((dest / "clip.mp4").read_bytes(), b"original")

    def test_the_destination_holds_no_partial_names_while_staging(self):
        # The whole point: a download in progress is invisible to Dropbox and
        # to the Premiere watcher, because it lives under .fg-tmp.
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            stage = config.ensure_stage_dir(dest)
            (stage / "clip.mp4.part").write_bytes(b"half")
            visible = [p.name for p in dest.iterdir() if p.name != ".fg-tmp"]
            self.assertEqual(visible, [])

    def test_sweep_removes_leftover_staging_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            stage = config.ensure_stage_dir(dest)
            (stage / "orphan.mp4.part").write_bytes(b"junk")
            runner.sweep_stage_dir(dest)
            self.assertFalse(stage.exists())

    def test_sweep_is_safe_when_there_is_nothing_to_sweep(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner.sweep_stage_dir(Path(tmp))  # must not raise
```

Add `from footagegrab import config, runner` and `import tempfile` / `from pathlib import Path` to the test file's imports if absent.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd host && python3 -m pytest tests/test_runner.py -q`
Expected: FAIL with `AttributeError: 'Runner' object has no attribute '_deliver'`

- [ ] **Step 3: Implement delivery and sweeping**

Add to `runner.py`, at module level:

```python
def sweep_stage_dir(out_dir):
    """Remove a staging folder left by a crash. Safe when absent."""
    stage = Path(out_dir) / config.STAGE_DIR_NAME
    if not stage.is_dir():
        return
    try:
        shutil.rmtree(stage)
    except OSError:
        log.warning("could not sweep %s", stage, exc_info=True)
```

Add `import shutil` to the imports.

Add to the `DownloadRunner` class:

```python
    @staticmethod
    def _deliver(staged_path, out_dir):
        """Move a finished file out of staging. Returns its final path.

        os.replace is atomic within a volume, so the destination goes from
        "no such file" to "complete file" with nothing observable between —
        which is what keeps Dropbox and the Premiere watcher from ever seeing
        a partial clip. The unique name is resolved here, at delivery time,
        because post-processing can change the extension.
        """
        staged_path = Path(staged_path)
        final = naming.unique_path(out_dir, staged_path.stem, staged_path.suffix)
        os.replace(staged_path, final)
        return final
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd host && python3 -m pytest tests/test_runner.py -q`
Expected: PASS

- [ ] **Step 5: Wire staging into `download()`**

In `runner.py`, after `out_dir = config.ensure_output_dir(cfg)` (`:39`), add:

```python
        stage_dir = config.ensure_stage_dir(out_dir)
```

Change `_plan_path` usage at `:47` so the name is reserved against the destination but the file is written in staging:

```python
        planned = self._plan_path(job, cfg, out_dir, quality)
        path = stage_dir / planned.name
```

At the completion block (`:129-136`), deliver before returning:

```python
        if cfg.get("compat_transcode", True):
            final, cerr = self._ensure_compat(job, Path(final), ffmpeg, on_progress)
            if cerr == "canceled":
                Path(final).unlink(missing_ok=True)
                return False, "canceled", ""
        try:
            final = self._deliver(Path(final), out_dir)
        except OSError as exc:
            Path(final).unlink(missing_ok=True)
            return False, f"could not deliver to {out_dir}: {exc}", ""
        log.info("job %s done: %s", job.id, final)
        return True, "", str(final)
```

In `_run_fallback` (`:191-193`), replace the locally-created `.fg-tmp` with the staging folder that already exists — delete these three lines:

```python
        tmp_dir = Path(out_dir) / ".fg-tmp"
        try:
            tmp_dir.mkdir(exist_ok=True)
```

and use `tmp_dir = config.ensure_stage_dir(out_dir)` instead, keeping the rest of the function unchanged. Delete `_cleanup_fallback_tmp`'s `Path(tmp_path).parent.rmdir()` line (`:241`) — the staging folder is now shared and must not be removed mid-job.

- [ ] **Step 6: Run the whole host suite**

Run: `cd host && python3 -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add host/footagegrab/runner.py host/tests/test_runner.py
git commit -m "feat(host): stage downloads and deliver them atomically"
```

---

### Task 4: Destination messages in the router

**Files:**
- Modify: `host/footagegrab/router.py:23-36` (handler table), `:68-73` (`_choose_folder` → `_add_destination`), `:75-123` (`_enqueue`), `host/footagegrab/jobs.py` (Job field)
- Test: `host/tests/test_host_e2e.py`

**Interfaces:**
- Consumes: `config.add_destination`, `config.remove_destination`, `config.select_destination`, `config.destinations` from Task 1.
- Produces: message types `set_destination`, `add_destination`, `remove_destination`; `Job.destination_id: str`.

- [ ] **Step 1: Write the failing tests**

Add to `host/tests/test_host_e2e.py`:

```python
    def test_set_destination_selects_an_existing_folder(self):
        cfg, a = config.add_destination(str(Path(self.tmp.name) / "a"))
        cfg, b = config.add_destination(str(Path(self.tmp.name) / "b"))
        reply = self.router.handle({"id": 1, "type": "set_destination", "dest_id": a["id"]})
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["config"]["destination_id"], a["id"])

    def test_set_destination_rejects_an_unknown_id(self):
        reply = self.router.handle({"id": 1, "type": "set_destination", "dest_id": "nope"})
        self.assertFalse(reply["ok"])
        self.assertIn("unknown destination", reply["error"])

    def test_remove_destination_reports_the_new_selection(self):
        cfg, a = config.add_destination(str(Path(self.tmp.name) / "a"))
        cfg, b = config.add_destination(str(Path(self.tmp.name) / "b"))
        reply = self.router.handle({"id": 1, "type": "remove_destination", "dest_id": b["id"]})
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["config"]["destination_id"], a["id"])

    def test_choose_folder_message_is_gone(self):
        reply = self.router.handle({"id": 1, "type": "choose_folder"})
        self.assertFalse(reply["ok"])
        self.assertIn("unknown message type", reply["error"])

    def test_enqueue_carries_a_per_job_destination_override(self):
        cfg, a = config.add_destination(str(Path(self.tmp.name) / "a"))
        reply = self.router.handle({
            "id": 1, "type": "enqueue", "mode": "full",
            "url": "https://youtube.com/watch?v=abc", "destination_id": a["id"],
        })
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["jobs"][0]["destination_id"], a["id"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd host && python3 -m pytest tests/test_host_e2e.py -q`
Expected: FAIL — `unknown message type: set_destination`

- [ ] **Step 3: Implement**

In `router.py`, replace `"choose_folder": self._choose_folder,` in the handler table with:

```python
            "add_destination": self._add_destination,
            "set_destination": self._set_destination,
            "remove_destination": self._remove_destination,
```

Replace `_choose_folder` with:

```python
    def _add_destination(self, msg):
        path, error = system.choose_folder()
        if path is None:
            raise AppError(error if error != "canceled" else "canceled")
        cfg, entry = config.add_destination(path, label=msg.get("label") or "")
        return {"config": cfg, "destination": entry}

    def _set_destination(self, msg):
        cfg, error = config.select_destination(str(msg.get("dest_id") or ""))
        if error:
            raise AppError(error)
        return {"config": cfg}

    def _remove_destination(self, msg):
        cfg, error = config.remove_destination(str(msg.get("dest_id") or ""))
        if error:
            raise AppError(error)
        return {"config": cfg}
```

In `_enqueue`, add the override to `common`:

```python
            "destination_id": str(msg.get("destination_id") or "")[:16],
```

In `jobs.py`, add `destination_id: str = ""` to the `Job` dataclass and include it in `to_dict()` alongside the other fields.

In `runner.py`'s `download()`, honour the override — replace `out_dir = config.ensure_output_dir(cfg)` with:

```python
        if getattr(job, "destination_id", ""):
            cfg = dict(cfg, destination_id=job.destination_id)
        try:
            out_dir = config.ensure_output_dir(cfg)
        except OSError as exc:
            return False, f"output folder unavailable: {exc}", ""
```

- [ ] **Step 4: Write the failing tests for enqueue-time validation**

The spec requires a bad destination to fail *before* a long download, with a message naming the folder, and an empty list to say so plainly. Add to `test_host_e2e.py`:

```python
    def test_enqueue_refuses_when_no_destination_is_set(self):
        reply = self.router.handle({"id": 1, "type": "enqueue", "mode": "full",
                                    "url": "https://youtube.com/watch?v=abc"})
        self.assertFalse(reply["ok"])
        self.assertIn("no destination set", reply["error"])

    def test_enqueue_refuses_an_unwritable_destination_and_names_it(self):
        blocked = Path(self.tmp.name) / "blocked"
        blocked.mkdir()
        blocked.chmod(0o500)
        try:
            config.add_destination(str(blocked))
            reply = self.router.handle({"id": 1, "type": "enqueue", "mode": "full",
                                        "url": "https://youtube.com/watch?v=abc"})
            self.assertFalse(reply["ok"])
            self.assertIn(str(blocked), reply["error"])
        finally:
            blocked.chmod(0o700)
```

- [ ] **Step 5: Run them to verify they fail**

Run: `cd host && python3 -m pytest tests/test_host_e2e.py -q`
Expected: FAIL — enqueue currently accepts both.

- [ ] **Step 6: Implement the check**

In `router.py`'s `_enqueue`, after the URL validation and before building `common`:

```python
        cfg_now = config.load()
        override = str(msg.get("destination_id") or "")
        if override:
            cfg_now = dict(cfg_now, destination_id=override)
        if not config.selected_destination(cfg_now):
            raise AppError("no destination set — add a folder in the extension first")
        try:
            config.ensure_output_dir(cfg_now)
        except OSError as exc:
            raise AppError(f"destination unavailable: {exc}") from None
```

`ensure_output_dir` raises `OSError(f"not writable: {path}")`, so the folder is named in the message. The equivalent check stays in `download()` as a backstop, because a folder can disappear between enqueue and run.

- [ ] **Step 7: Sweep leftover staging folders at host startup**

The spec promises a crash-leftover sweep. In `footagegrab_host.py`, right after `runner = DownloadRunner(config.load, pot=pot)` (`:53`):

```python
    # A crash can leave a partial file in the staging folder. Nothing in there
    # is resumable — yt-dlp re-extracts on every run — so clear it at startup.
    try:
        startup_cfg = config.load()
        if config.selected_destination(startup_cfg):
            sweep_stage_dir(config.ensure_output_dir(startup_cfg))
    except OSError:
        log.warning("could not sweep the staging folder at startup", exc_info=True)
```

Change the existing import at `footagegrab_host.py:26` from
`from footagegrab.runner import DownloadRunner  # noqa: E402` to
`from footagegrab.runner import DownloadRunner, sweep_stage_dir  # noqa: E402`.

- [ ] **Step 8: Run the whole suite**

Run: `cd host && python3 -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add host/footagegrab/router.py host/footagegrab/jobs.py host/footagegrab/runner.py host/footagegrab_host.py host/tests/
git commit -m "feat(host): add destination selection messages and validate at enqueue"
```

---

### Task 5: "Save to" picker in the extension

**Files:**
- Modify: `extension/popup/popup.html:55-65`, `extension/popup/settings.js:42-63` (paint) and `:79-87` (wire)
- Test: manual, in the browser — the popup has no unit-test harness for DOM code

**Interfaces:**
- Consumes: host messages `set_destination`, `add_destination`, `remove_destination` from Task 4; `config.destinations` / `config.destination_id` in the returned config.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Replace the folder card markup**

In `popup.html`, replace lines 55-65 with:

```html
      <div class="card-title">Save to</div>
      <div class="folder-row">
        <select id="destination-select" class="folder-path"></select>
      </div>
      <div class="row-actions">
        <button id="add-destination" class="btn">Add folder…</button>
        <button id="open-folder" class="btn btn-ghost">Open in Finder</button>
        <button id="remove-destination" class="btn btn-ghost">Remove</button>
      </div>
      <p class="hint">Downloads go straight here — they are assembled out of sight
      and appear only once complete, so a half-finished clip never reaches Dropbox
      or Premiere. The picker opens behind this popup; reopen it to confirm.</p>
```

- [ ] **Step 2: Render the list in `paint()`**

In `settings.js`, replace the claim-aware `folder-path` block (`:44-51`) with:

```js
  const select = $("destination-select");
  const dests = Array.isArray(config.destinations) ? config.destinations : [];
  select.innerHTML = "";
  for (const d of dests) {
    const opt = document.createElement("option");
    opt.value = d.id;
    opt.textContent = `${d.label} — ${d.path}`;
    select.appendChild(opt);
  }
  if (dests.length) {
    select.value = config.destination_id || dests[0].id;
  } else {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No folder set — add one";
    select.appendChild(opt);
  }
  $("remove-destination").disabled = dests.length === 0;
```

- [ ] **Step 3: Wire the controls**

In `wire()`, replace the `choose-folder` listener with:

```js
  $("destination-select").addEventListener("change", async e => {
    if (!e.target.value) return;
    const res = await host({ type: "set_destination", dest_id: e.target.value }).catch(() => null);
    if (res?.ok) { config = res.config; paint(); markSaved(); }
  });

  $("add-destination").addEventListener("click", () => {
    // The native picker steals focus, which closes this popup; the host still
    // saves the chosen folder — the hint text tells the user to reopen.
    host({ type: "add_destination" }, 240000).then(res => {
      if (res?.ok) { config = res.config; paint(); markSaved(); }
    });
  });

  $("remove-destination").addEventListener("click", async () => {
    const id = $("destination-select").value;
    if (!id) return;
    const res = await host({ type: "remove_destination", dest_id: id }).catch(() => null);
    if (res?.ok) { config = res.config; paint(); markSaved(); }
  });
```

- [ ] **Step 4: Load the unpacked extension and check it by hand**

Open `chrome://extensions`, reload the FootageGrab extension, open the popup, and confirm: the dropdown lists your saved folders; `Add folder…` opens the native picker and the new folder appears selected after reopening the popup; switching the dropdown persists across a popup close/open; `Remove` is disabled when the list is empty.

- [ ] **Step 5: Commit**

```bash
git add extension/popup/popup.html extension/popup/settings.js
git commit -m "feat(extension): pick the download destination from a saved list"
```

---

### Task 6: Premiere panel reads the selection

Drops project-follow and ports the readiness hardening into the repo — it currently exists **only** in the installed copy at `~/Library/Application Support/Adobe/CEP/extensions/FootageGrabBridge`, so a reinstall from this repo would silently revert it.

**Files:**
- Modify: `premiere/js/watchcore.js` (harden `planTick`, delete `projectFootageDir`), `premiere/js/panel.js` (`resolveDir`, `listEntries`, remove `syncProjectDir` and the follow toggle), `premiere/index.html` (remove `follow-toggle`)
- Test: `premiere/tests/watchcore.test.js`

**Interfaces:**
- Consumes: `destinations` / `destination_id` in `config.json` from Task 1.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing tests**

Replace the contents of `premiere/tests/watchcore.test.js` with the suite below. It is the verified version — all nine cases pass against the hardened implementation.

```js
const { test } = require('node:test');
const assert = require('node:assert');
const W = require('../js/watchcore.js');

const never = () => false;
const f = (name, size, extra = {}) => ({ name, path: '/w/' + name, size, mtimeMs: 1000, ...extra });

function run(entries, ticks, seen = never) {
  let state = {};
  let last;
  for (let i = 0; i < ticks; i++) {
    last = W.planTick(entries, state, seen);
    state = last.sizes;
  }
  return last;
}

test('a settled local file imports, but only after STABLE_TICKS observations', () => {
  const e = [f('clip.mp4', 5000)];
  assert.strictEqual(run(e, 1).ready.length, 0, 'first sighting must not import');
  assert.strictEqual(run(e, 2).ready.length, 0, 'one match is not enough');
  assert.strictEqual(run(e, 3).ready.length, 1, 'settles after STABLE_TICKS matches');
});

test('a dataless cloud placeholder never imports, however long it sits', () => {
  assert.strictEqual(run([f('online-only.mp4', 697415, { hasData: false })], 10).ready.length, 0);
});

test('a file still growing never settles', () => {
  let state = {};
  let ready = [];
  for (let size = 1000; size <= 9000; size += 1000) {
    const r = W.planTick([f('growing.mp4', size)], state, never);
    state = r.sizes;
    ready = r.ready;
  }
  assert.strictEqual(ready.length, 0);
});

test('a finished name is held back while its .part sibling still exists', () => {
  const mid = [f('clip.mp4', 5000), f('clip.mp4.part', 120)];
  assert.strictEqual(run(mid, 5).ready.length, 0, 'sibling means still assembling');
  assert.strictEqual(run([f('clip.mp4', 5000)], 3).ready.length, 1, 'imports once sibling is gone');
});

test('temp markers are still excluded by name', () => {
  assert.strictEqual(W.isCandidateName('clip.mp4.part'), false);
  assert.strictEqual(W.isCandidateName('clip.ytdl'), false);
  assert.strictEqual(W.isCandidateName('clip.mp4'), true);
});

test('zero-byte files never settle', () => {
  assert.strictEqual(run([f('empty.mp4', 0)], 5).ready.length, 0);
});

test('already-seen files are skipped entirely', () => {
  assert.strictEqual(run([f('clip.mp4', 5000)], 5, () => true).ready.length, 0);
});

test('legacy bare-number state from an older run is tolerated', () => {
  const e = [f('clip.mp4', 5000)];
  const r1 = W.planTick(e, { '/w/clip.mp4': 5000 }, never);
  assert.strictEqual(r1.ready.length, 0, 'legacy state restarts the counter, does not crash');
  assert.strictEqual(W.planTick(e, r1.sizes, never).ready.length, 1);
});

test('Windows (blocks unreported) still imports normally', () => {
  assert.strictEqual(run([f('clip.mp4', 5000, { hasData: undefined })], 3).ready.length, 1);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd premiere && node --test tests/watchcore.test.js`
Expected: FAIL — the current `planTick` imports on the first stable observation and ignores `hasData`.

- [ ] **Step 3: Port the hardened `planTick`**

Copy `js/watchcore.js` from the installed extension, which already holds the verified implementation:

```bash
cp ~/Library/Application\ Support/Adobe/CEP/extensions/FootageGrabBridge/js/watchcore.js premiere/js/watchcore.js
```

Then delete `projectFootageDir` from that file and from the exported `api` object — project-follow is gone.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd premiere && node --test tests/watchcore.test.js`
Expected: PASS, 9 tests

- [ ] **Step 5: Point the panel at the selected destination**

In `panel.js`, replace `resolveDir()` with:

```js
  // The extension owns the destination now; the panel follows it. A manual
  // override still wins, for the odd case where you want to watch elsewhere.
  function resolveDir() {
    if (dirOverride) return expandTilde(dirOverride);
    try {
      var cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
      var list = (cfg && cfg.destinations) || [];
      for (var i = 0; i < list.length; i++) {
        if (list[i] && list[i].id === cfg.destination_id) return expandTilde(list[i].path);
      }
      if (list.length && list[0].path) return expandTilde(list[0].path);
    } catch (e) { /* no config yet — fall through */ }
    return expandTilde(DEFAULT_DIR);
  }
```

Delete `syncProjectDir`, `refreshProjectPath`'s use of it, the `followProject` variable, its `saveSettings` entry, its `ui.follow` wiring, and `HEARTBEAT_S`. Remove the `follow-toggle` element from `premiere/index.html`.

Add `hasData` to `listEntries` so the placeholder check has input:

```js
        var st = fs.statSync(full);
        if (st.isFile()) {
          // A dataless cloud placeholder (Dropbox/iCloud online-only) reports
          // its full logical size while occupying zero blocks. Importing one
          // hands Premiere a file with no frames in it. Windows doesn't report
          // blocks, so undefined means "can't tell" and counts as real data.
          var hasData = typeof st.blocks === "number" ? st.blocks > 0 : true;
          entries.push({ name: names[i], path: full, size: st.size, mtimeMs: st.mtimeMs, hasData: hasData });
        }
```

- [ ] **Step 6: Reinstall the panel and confirm it follows the selection**

Run `install/install-premiere.sh`, restart Premiere, open the panel, and confirm the watched path shown in the panel matches the destination selected in the extension. Switch the destination in the popup and confirm the panel retargets within a few seconds.

- [ ] **Step 7: Commit**

```bash
git add premiere/
git commit -m "feat(panel): follow the extension's destination and harden readiness checks"
```

---

### Task 7: Phase 1 local verification

No code. This is the gate before Phase 2 (Windows, installers, other editors) and before deleting the mover.

**Files:**
- Modify: `docs/superpowers/specs/2026-08-15-selectable-destinations-design.md` (status line)

- [ ] **Step 1: Stand down the mover, without deleting it**

```bash
launchctl bootout gui/$(id -u)/com.ziscol.footagegrab-mover
launchctl print gui/$(id -u)/com.ziscol.footagegrab-mover 2>&1 | tail -1
```
Expected: "Could not find service". The scripts stay on disk until Phase 2.

- [ ] **Step 2: Grab a segment straight into the Dropbox folder**

In the extension, select the Chris Tucker Dropbox `Videos` folder, set quality to **Best**, mark a short in/out on a YouTube video, and grab.

- [ ] **Step 3: Confirm nothing partial is ever visible**

While it downloads, run repeatedly:
```bash
ls -a "$HOME/Library/CloudStorage/Dropbox-Ziscolwp/Youtube Videos/Chris Tucker Funny Moments/Videos"
```
Expected: only `.fg-tmp` and previously delivered clips. **No `.part` file and no partially-written `.mp4` under its final name at any point.** When the grab completes the finished clip appears in one step.

- [ ] **Step 4: Confirm Premiere imports it and the media is sound**

The panel should import the clip within a few seconds. Scrub it in Premiere end to end and confirm no "media offline" and no frame-substitution error.

- [ ] **Step 5: Confirm a cancelled grab leaves nothing behind**

Start another grab and cancel it mid-download. Expected: the destination is unchanged, and `.fg-tmp` holds no leftovers after the next host start.

- [ ] **Step 6: Confirm the 720p-only case now works**

Grab from `https://www.youtube.com/watch?v=n5sv4C1bMqc` — the 2011 clip that failed with "Requested format is not available" under a fixed 1080 setting. Expected: succeeds at 720p.

- [ ] **Step 7: Record the result and commit**

Update the spec's status line to `Phase 1 verified <date>` (or record what failed), then:

```bash
git add docs/superpowers/specs/2026-08-15-selectable-destinations-design.md
git commit -m "docs(specs): record Phase 1 verification result"
```

- [ ] **Step 8: Stop**

Phase 2 — Windows verification, installer updates, distribution, and deleting `~/Ziscol Media Projects/footagegrab-mover/` plus the launch agent and scheduled task — is a separate plan. Do not start it here.
