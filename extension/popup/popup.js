// Popup boot: connect to the host, paint status, wire tabs and live updates.

import { host } from "./api.js";
import * as queue from "./queue.js";
import * as settings from "./settings.js";

const $ = id => document.getElementById(id);

function setStatus(state, text) {
  const dot = $("status-dot");
  dot.className = "dot" + (state ? ` ${state}` : "");
  $("status-text").textContent = text;
}

function wireTabs() {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => {
      for (const t of document.querySelectorAll(".tab")) t.classList.toggle("active", t === tab);
      $("view-queue").hidden = tab.dataset.tab !== "queue";
      $("view-settings").hidden = tab.dataset.tab !== "settings";
    });
  }
}

// One-click full-video grab of whatever tab the popup opened over.
async function wireGrabRow() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true }).catch(() => []);
  if (!tab?.url || !/^https?:\/\//i.test(tab.url)) return; // stays hidden
  $("grab-page").hidden = false;
  try { $("grab-host").textContent = new URL(tab.url).hostname; } catch (e) { /* keep dash */ }
  const btn = $("grab-page-btn");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Queuing…";
    const res = await host({ type: "enqueue", url: tab.url, mode: "full", source: "toolbar" })
      .catch(e => ({ ok: false, error: e.message }));
    btn.textContent = res?.ok ? "Queued ✓" : "Failed";
    if (!res?.ok) btn.title = res?.error || "";
    setTimeout(() => { btn.disabled = false; btn.textContent = "Grab"; }, 1800);
    queue.refresh();
  });
}

async function boot() {
  wireTabs();
  settings.wire();
  queue.refresh();
  wireGrabRow();

  const ping = await host({ type: "ping" }, 20000).catch(e => ({ ok: false, error: e.message }));
  if (ping?.ok) {
    setStatus("ok", `Host v${ping.host_version}`);
    settings.setConfig(ping.config);
    settings.paintHealth(ping.health);
    $("setup-help").hidden = true;
    if (!ping.health?.ytdlp?.found || !ping.health?.ffmpeg?.found) {
      setStatus("down", "Tools missing — see Settings");
    }
  } else {
    setStatus("down", "Host not reachable");
    $("setup-help").hidden = false;
    // Jump straight to the tab that explains how to fix it.
    document.querySelector('[data-tab="settings"]').click();
  }
}

chrome.runtime.onMessage.addListener(req => {
  if (req?.kind === "job_update") queue.updateJob(req.job);
  else if (req?.kind === "host_down") setStatus("down", "Host disconnected");
  else if (req?.kind === "host_up") setStatus("ok", "Host connected");
});

boot();
