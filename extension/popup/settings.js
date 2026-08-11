// Settings tab: reads/writes host config, shows tool health, updates yt-dlp.

import { host } from "./api.js";

let config = null;
let saveTimer = null;

const $ = id => document.getElementById(id);

const PREVIEW_FIELDS = {
  title: "Oprah Interview", id: "dQw4w9WgXcQ", site: "youtube", n: "2",
  start: "00.42", end: "01.18", date: "2026-08-11", quality: "best",
};

function previewName(template) {
  let name = String(template || "").replace(/\{(\w+)\}/g, (_, k) => PREVIEW_FIELDS[k] ?? "");
  name = name.replace(/_+/g, "_").replace(/^[_.-]+|[_.-]+$/g, "");
  return (name || "clip") + ".mp4";
}

function markSaved() {
  const tick = $("save-tick");
  tick.hidden = false;
  tick.style.animation = "none";
  void tick.offsetWidth;
  tick.style.animation = "";
  setTimeout(() => { tick.hidden = true; }, 1700);
}

function patch(fields) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const res = await host({ type: "set_config", patch: fields }).catch(() => null);
    if (res?.ok) {
      config = res.config;
      paint();
      markSaved();
    }
  }, 350);
}

export function paint() {
  if (!config) return;
  $("folder-path").textContent = config.output_dir || "—";
  for (const b of $("quality-seg").querySelectorAll("button")) {
    b.classList.toggle("active", b.dataset.q === config.quality);
  }
  $("accurate-toggle").checked = !!config.accurate_cut;
  $("compat-toggle").checked = config.compat_transcode !== false;
  $("asknames-toggle").checked = !!config.ask_names;
  $("cookies-select").value = config.cookies_browser || "none";
  if (document.activeElement !== $("tpl-segment")) $("tpl-segment").value = config.template_segment;
  if (document.activeElement !== $("tpl-full")) $("tpl-full").value = config.template_full;
  $("tpl-segment-preview").textContent = previewName(config.template_segment);
  $("tpl-full-preview").textContent = previewName(config.template_full);
}

export function paintHealth(health) {
  $("ytdlp-version").textContent = health?.ytdlp?.found
    ? health.ytdlp.version : "missing — brew install yt-dlp";
  $("ffmpeg-version").textContent = health?.ffmpeg?.found
    ? (health.ffmpeg.version || "").replace(/^ffmpeg version /, "").split(" ")[0]
    : "missing — brew install ffmpeg";
  $("logs-path").textContent = health?.logs || "—";
}

export function setConfig(cfg) {
  config = cfg;
  paint();
}

export function wire() {
  $("choose-folder").addEventListener("click", async () => {
    // The native picker steals focus, which closes this popup; the host still
    // saves the chosen folder — the hint text tells the user to reopen.
    host({ type: "choose_folder" }, 240000).then(res => {
      if (res?.ok) { config = res.config; paint(); markSaved(); }
    });
  });
  $("open-folder").addEventListener("click", () => host({ type: "open_folder" }));

  $("quality-seg").addEventListener("click", e => {
    const b = e.target.closest("button[data-q]");
    if (!b) return;
    for (const x of $("quality-seg").querySelectorAll("button")) {
      x.classList.toggle("active", x === b);
    }
    patch({ quality: b.dataset.q });
  });

  $("accurate-toggle").addEventListener("change", e => patch({ accurate_cut: e.target.checked }));
  $("compat-toggle").addEventListener("change", e => patch({ compat_transcode: e.target.checked }));
  $("asknames-toggle").addEventListener("change", e => patch({ ask_names: e.target.checked }));
  $("cookies-select").addEventListener("change", e => patch({ cookies_browser: e.target.value }));

  for (const [inputId, key, previewId] of [
    ["tpl-segment", "template_segment", "tpl-segment-preview"],
    ["tpl-full", "template_full", "tpl-full-preview"],
  ]) {
    $(inputId).addEventListener("input", e => {
      $(previewId).textContent = previewName(e.target.value);
      if (e.target.value.trim()) patch({ [key]: e.target.value.trim() });
    });
  }

  $("update-ytdlp").addEventListener("click", async () => {
    const btn = $("update-ytdlp");
    const out = $("update-output");
    btn.disabled = true;
    btn.textContent = "Updating…";
    const res = await host({ type: "update_ytdlp" }, 300000).catch(e => ({ ok: false, output: e.message }));
    out.textContent = res?.output || res?.error || "No output";
    out.hidden = false;
    btn.disabled = false;
    btn.textContent = "Update yt-dlp";
  });
}
