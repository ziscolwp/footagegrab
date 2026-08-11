// Ambient toasts inside the player: queued / downloading / saved / failed.
// One card per job, updated in place as the host pushes progress.
(function () {
  "use strict";
  window.FG = window.FG || {};
  const T = window.FG.time;

  let container = null;
  const cards = new Map(); // job id -> element
  const MAX_VISIBLE = 4;

  function mount(playerEl) {
    unmount();
    container = document.createElement("div");
    container.className = "fg-toasts";
    playerEl.appendChild(container);
  }

  function unmount() {
    container?.remove();
    container = null;
    cards.clear();
  }

  function trim() {
    while (container && container.children.length > MAX_VISIBLE) {
      const el = container.firstElementChild;
      for (const [id, card] of cards) if (card === el) cards.delete(id);
      el.remove();
    }
  }

  function show(kind, text, opts = {}) {
    if (!container) return null;
    const el = document.createElement("div");
    el.className = `fg-toast fg-toast-${kind}`;
    const body = document.createElement("div");
    body.className = "fg-toast-body";
    body.textContent = text;
    el.appendChild(body);
    if (opts.actions?.length) {
      const row = document.createElement("div");
      row.className = "fg-toast-actions";
      for (const a of opts.actions) {
        const b = document.createElement("button");
        b.className = "fg-btn fg-btn-ghost";
        b.textContent = a.label;
        b.addEventListener("click", () => { a.fn(); el.remove(); });
        row.appendChild(b);
      }
      el.appendChild(row);
    }
    container.appendChild(el);
    trim();
    const timeout = opts.timeout ?? (kind === "error" ? 0 : 4000);
    if (timeout) setTimeout(() => el.remove(), timeout);
    return el;
  }

  function jobMeta(job) {
    if (job.mode === "segment" && job.start != null) {
      return `${T.fmtClock(job.start)}–${T.fmtClock(job.end)} · ${T.fmtDuration(job.end - job.start)}`;
    }
    return "Full video";
  }

  function sendHost(msg) {
    chrome.runtime.sendMessage({ cmd: "host", msg }).catch(() => {});
  }

  function upsertJob(job) {
    if (!container) return;
    let el = cards.get(job.id);
    if (!el) {
      el = document.createElement("div");
      el.className = "fg-toast fg-job";
      cards.set(job.id, el);
      container.appendChild(el);
      trim();
    }
    el.dataset.state = job.state;

    const title = (job.title || job.video_id || "Clip").slice(0, 60);
    const meta = jobMeta(job);
    let stateHtml = "";
    if (job.state === "queued") {
      stateHtml = `<div class="fg-job-status">Queued</div>`;
    } else if (job.state === "running") {
      const pct = Math.round((job.progress || 0) * 100);
      const bar = job.progress > 0
        ? `<div class="fg-bar"><div class="fg-bar-fill" style="width:${pct}%"></div></div>`
        : `<div class="fg-bar fg-bar-indeterminate"><div class="fg-bar-fill"></div></div>`;
      const label = job.stage === "processing" ? "Processing" : (pct > 0 ? `${pct}%` : "Downloading");
      stateHtml = `<div class="fg-job-status">${label}</div>${bar}`;
    } else if (job.state === "done") {
      stateHtml = `<div class="fg-job-status fg-ok">Saved to footage folder</div>`;
    } else if (job.state === "failed") {
      const err = (job.error || "Download failed").slice(0, 140);
      stateHtml = `<div class="fg-job-status fg-err"></div>`;
      // error text is set via textContent below to avoid HTML injection
      el.dataset.err = err;
    } else if (job.state === "canceled") {
      stateHtml = `<div class="fg-job-status">Canceled</div>`;
    }

    el.innerHTML = `
      <div class="fg-toast-body">
        <div class="fg-job-title"></div>
        <div class="fg-job-meta"></div>
        ${stateHtml}
      </div>
      <div class="fg-toast-actions"></div>`;
    el.querySelector(".fg-job-title").textContent = title;
    el.querySelector(".fg-job-meta").textContent = meta;
    if (job.state === "failed") {
      const status = el.querySelector(".fg-job-status");
      status.textContent = err_short(job);
      status.title = job.error || "";
    }

    const actions = el.querySelector(".fg-toast-actions");
    const addBtn = (label, fn, cls = "fg-btn fg-btn-ghost") => {
      const b = document.createElement("button");
      b.className = cls;
      b.textContent = label;
      b.addEventListener("click", fn);
      actions.appendChild(b);
    };
    if (job.state === "running" || job.state === "queued") {
      addBtn("✕", () => sendHost({ type: "cancel", job_id: job.id }));
    } else if (job.state === "done") {
      addBtn("Reveal", () => sendHost({ type: "reveal", path: job.file }));
      setTimeout(() => { el.remove(); cards.delete(job.id); }, 8000);
    } else if (job.state === "failed") {
      addBtn("Retry", () => { sendHost({ type: "retry", job_id: job.id }); el.remove(); cards.delete(job.id); });
      addBtn("✕", () => { el.remove(); cards.delete(job.id); });
    } else if (job.state === "canceled") {
      setTimeout(() => { el.remove(); cards.delete(job.id); }, 4000);
    }
  }

  function err_short(job) {
    return (job.error || "Download failed").slice(0, 140);
  }

  window.FG.toasts = { mount, unmount, show, upsertJob };
})();
