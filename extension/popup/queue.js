// Queue tab: live jobs from the host plus recent history from disk.

import { fmtClock, host } from "./api.js";

const TERMINAL = new Set(["done", "failed", "canceled"]);
let known = new Map(); // job id -> job

function meta(job) {
  if (job.mode === "segment" && job.start != null) {
    return `${fmtClock(job.start)}–${fmtClock(job.end)} · ${fmtClock(job.end - job.start)}`;
  }
  return "Full video";
}

function jobRow(job) {
  const el = document.createElement("div");
  el.className = "job";
  el.dataset.id = job.id;

  const top = document.createElement("div");
  top.className = "job-top";
  const title = document.createElement("div");
  title.className = "job-title";
  title.textContent = job.title || job.video_id || "Clip";
  title.title = job.title || "";
  top.appendChild(title);

  const addBtn = (label, onClick) => {
    const b = document.createElement("button");
    b.className = "btn-mini";
    b.textContent = label;
    b.addEventListener("click", onClick);
    top.appendChild(b);
  };

  if (job.state === "queued" || job.state === "running") {
    addBtn("Cancel", () => host({ type: "cancel", job_id: job.id }));
  } else if (job.state === "failed" || job.state === "canceled") {
    addBtn("Retry", () => host({ type: "retry", job_id: job.id }).then(refresh));
  } else if (job.state === "done" && job.file) {
    addBtn("Reveal", () => host({ type: "reveal", path: job.file }));
  }
  el.appendChild(top);

  const m = document.createElement("div");
  m.className = "job-meta";
  m.textContent = meta(job);
  el.appendChild(m);

  const status = document.createElement("div");
  status.className = "job-status";
  if (job.state === "running") {
    const pct = Math.round((job.progress || 0) * 100);
    status.textContent = job.stage === "processing" ? "Processing…" : (pct ? `${pct}%` : "Downloading…");
    const bar = document.createElement("div");
    bar.className = "bar" + (pct ? "" : " bar-indeterminate");
    const fill = document.createElement("div");
    fill.className = "bar-fill";
    if (pct) fill.style.width = `${pct}%`;
    bar.appendChild(fill);
    el.appendChild(status);
    el.appendChild(bar);
    return el;
  }
  if (job.state === "queued") status.textContent = "Queued";
  else if (job.state === "done") { status.textContent = "Saved"; status.classList.add("ok"); }
  else if (job.state === "canceled") status.textContent = "Canceled";
  else if (job.state === "failed") {
    status.textContent = (job.error || "Failed").slice(0, 120);
    status.title = job.error || "";
    status.classList.add("err");
  }
  el.appendChild(status);
  return el;
}

function render() {
  const jobs = [...known.values()];
  const active = jobs.filter(j => !TERMINAL.has(j.state))
    .sort((a, b) => (a.created || 0) - (b.created || 0));
  const recent = jobs.filter(j => TERMINAL.has(j.state))
    .sort((a, b) => (b.finished || b.created || 0) - (a.finished || a.created || 0))
    .slice(0, 25);

  const activeList = document.getElementById("active-list");
  const recentList = document.getElementById("recent-list");
  activeList.textContent = "";
  recentList.textContent = "";

  if (!active.length) {
    const e = document.createElement("div");
    e.className = "empty";
    e.textContent = "Nothing downloading. On a YouTube video, press I to mark an In point.";
    activeList.appendChild(e);
  } else {
    active.forEach(j => activeList.appendChild(jobRow(j)));
  }

  if (!recent.length) {
    const e = document.createElement("div");
    e.className = "empty";
    e.textContent = "Grabbed clips will show up here.";
    recentList.appendChild(e);
  } else {
    recent.forEach(j => recentList.appendChild(jobRow(j)));
  }
}

export function updateJob(job) {
  known.set(job.id, job);
  render();
}

export async function refresh() {
  known = new Map();
  const [live, history] = await Promise.all([
    host({ type: "jobs" }).catch(() => null),
    host({ type: "get_history" }).catch(() => null),
  ]);
  // History first so live session state wins for duplicate ids.
  for (const j of history?.history || []) known.set(j.id, j);
  for (const j of live?.jobs || []) known.set(j.id, j);
  render();
}
