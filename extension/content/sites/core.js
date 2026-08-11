// Shared engine for the per-site grab buttons: adapters register
// { name, matches(location), findVideoContainers(root), resolveUrl(container) }
// and this mounts one FG button per video container, wired to a full-video
// enqueue. Adapters are expendable; the context menu always works without them.
(function () {
  "use strict";
  window.FG = window.FG || {};

  const SCAN_MS = 1500;
  const initiated = new Set(); // job ids started from this tab
  let active = null;

  function register(adapter) {
    if (!active && adapter.matches(location)) start(adapter);
  }

  function start(adapter) {
    active = adapter;
    FG.toasts.configure({ quickDismiss: true }); // feeds fire many grabs
    remountToasts();
    chrome.runtime.onMessage.addListener(req => {
      if (req?.kind === "job_update" && initiated.has(req.job?.id)) {
        FG.toasts.upsertJob(req.job);
      }
    });
    const debounced = debounce(scan, 400);
    new MutationObserver(debounced).observe(document.body, { childList: true, subtree: true });
    setInterval(scan, SCAN_MS);
    scan();
  }

  function debounce(fn, ms) {
    let t = null;
    return () => {
      clearTimeout(t);
      t = setTimeout(fn, ms);
    };
  }

  // SPA rerenders can drop our nodes; cheap to re-check each scan.
  function remountToasts() {
    if (!document.querySelector(".fg-toasts")) {
      FG.toasts.mount(document.body, { fixed: true });
    }
  }

  function scan() {
    if (!active) return;
    remountToasts();
    const containers = active.findVideoContainers(document);
    for (const c of containers) if (c) ensureButton(c);
  }

  function ensureButton(container) {
    if (container.__fgBtn?.isConnected) return;
    // Mount on the parent: custom elements (shreddit-player) and <video>
    // don't render light-DOM children.
    const host = container.parentElement || container;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "fg-site-btn";
    btn.textContent = "FG ↓";
    btn.title = "Grab this video with FootageGrab";
    btn.addEventListener("click", e => {
      e.preventDefault();
      e.stopPropagation();
      grab(container, btn);
    });
    if (getComputedStyle(host).position === "static") host.style.position = "relative";
    host.appendChild(btn);
    container.__fgBtn = btn;
  }

  function grab(container, btn) {
    const url = active.resolveUrl(container);
    if (!url) {
      FG.toasts.show("error", "Couldn't resolve this post's link — try right-click → Grab video with FootageGrab");
      return;
    }
    btn.disabled = true;
    btn.textContent = "…";
    const reset = label => {
      btn.textContent = label;
      setTimeout(() => { btn.disabled = false; btn.textContent = "FG ↓"; }, 1600);
    };
    chrome.runtime.sendMessage({
      cmd: "host",
      msg: { type: "enqueue", url, mode: "full", source: "adapter" },
    }).then(res => {
      if (res?.ok) {
        for (const j of res.jobs || []) initiated.add(j.id);
        reset("✓");
      } else {
        FG.toasts.show("error", res?.error || "Could not queue the grab");
        reset("FG ↓");
      }
    }).catch(e => {
      FG.toasts.show("error", e.message);
      reset("FG ↓");
    });
  }

  window.FG.sites = { register };
})();
