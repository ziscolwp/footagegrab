// Background worker: owns the native messaging port, matches replies to
// requests, relays job pushes to YouTube tabs + popup, and keeps the badge
// showing the live job count. An open native port keeps this worker alive
// while downloads run (Chrome 116+).

const HOST_NAME = "com.footagegrab.host";
const DEFAULT_TIMEOUT_MS = 15000;
const MAX_TIMEOUT_MS = 300000;

let port = null;
let seq = 0;
const pending = new Map(); // request id -> {resolve, reject, timer}
const jobs = new Map(); // job id -> latest job dict (session mirror)

// Resolved async at worker start; the neutral default covers the window
// before the callback lands (and any OS the check doesn't recognise).
let installCmd = "the installer (install.sh / install.bat)";
chrome.runtime.getPlatformInfo(info => {
  installCmd = info.os === "win" ? "install\\install.bat" : "install/install.sh";
});

function connect() {
  if (port) return port;
  port = chrome.runtime.connectNative(HOST_NAME);
  port.onMessage.addListener(onHostMessage);
  port.onDisconnect.addListener(() => {
    const err = chrome.runtime.lastError?.message || "host disconnected";
    port = null;
    for (const [, p] of pending) p.reject(new Error(err));
    pending.clear();
    broadcast({ kind: "host_down", error: err });
  });
  return port;
}

function hostRequest(msg, timeoutMs = DEFAULT_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    let p;
    try {
      p = connect();
    } catch (e) {
      reject(new Error(`Native host not installed — run ${installCmd} and restart the browser`));
      return;
    }
    const id = ++seq;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error("The download host did not answer in time"));
    }, Math.min(timeoutMs, MAX_TIMEOUT_MS));
    pending.set(id, {
      resolve: v => { clearTimeout(timer); resolve(v); },
      reject: e => { clearTimeout(timer); reject(e); },
    });
    try {
      p.postMessage({ ...msg, id });
    } catch (e) {
      clearTimeout(timer);
      pending.delete(id);
      reject(e);
    }
  });
}

function onHostMessage(m) {
  if (!m) return;
  if (m.re != null) {
    const p = pending.get(m.re);
    if (p) {
      pending.delete(m.re);
      p.resolve(m);
    }
    return;
  }
  if (m.type === "job_update" && m.job) {
    jobs.set(m.job.id, m.job);
    updateBadge();
    broadcast({ kind: "job_update", job: m.job });
  } else if (m.type === "hello") {
    broadcast({ kind: "host_up", version: m.host_version });
  }
}

async function broadcast(payload) {
  try { await chrome.runtime.sendMessage(payload); } catch (e) { /* popup closed */ }
  try {
    // all tabs: YouTube + adapter sites have listeners; the rest just reject
    const tabs = await chrome.tabs.query({});
    await Promise.allSettled(tabs.map(t => chrome.tabs.sendMessage(t.id, payload)));
  } catch (e) { /* no tabs */ }
}

// ---- one-click grab surfaces: context menu, keyboard command ------------

function pickGrabUrl(info, tab) {
  // link beats media src beats page: right-clicking a tweet timestamp or a
  // Reddit title should grab that post, not the timeline. Media srcs are
  // often blob: URLs, which the http(s) filter rejects.
  const candidates = [info.linkUrl, info.srcUrl, info.pageUrl, tab && tab.url];
  for (const c of candidates) if (c && /^https?:\/\//i.test(c)) return c;
  return null;
}

async function grabUrl(url, source, tabId, customName = "") {
  if (!url) {
    flashInTab(tabId, false, "Nothing grabbable here");
    return;
  }
  try {
    const res = await hostRequest({ type: "enqueue", url, mode: "full", source, custom_name: customName });
    if (res?.ok) flashInTab(tabId, true, "Queued — grabbing video");
    else flashInTab(tabId, false, res?.error || "Could not queue the grab");
  } catch (e) {
    flashInTab(tabId, false, e.message);
  }
}

// "Ask for clip name" for pages without our content script: a plain injected
// prompt. Returns "" (auto name), a name, or null when the user cancels.
async function maybeAskName(tabId) {
  try {
    const cfg = await hostRequest({ type: "get_config" });
    if (!cfg?.ok || !cfg.config?.ask_names || tabId == null) return "";
    const [hit] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => window.prompt("FootageGrab — name this clip (blank = automatic):", ""),
    });
    if (hit?.result === null) return null;
    return (hit?.result || "").trim();
  } catch (e) {
    return ""; // restricted page — grab with the automatic name
  }
}

// Tiny injected ack toast: works on any page, no content script needed.
function flashInTab(tabId, ok, text) {
  if (tabId == null) return;
  chrome.scripting.executeScript({
    target: { tabId },
    func: (ok, text) => {
      const el = document.createElement("div");
      el.textContent = (ok ? "✓ " : "✕ ") + text;
      el.style.cssText =
        "position:fixed;right:16px;bottom:16px;z-index:2147483647;" +
        "background:rgba(16,16,18,0.92);color:#f2f2f0;" +
        `border:1px solid ${ok ? "rgba(23,201,100,0.5)" : "rgba(255,92,119,0.5)"};` +
        "border-radius:10px;padding:10px 14px;font:500 12.5px/1.4 Roboto,Arial,sans-serif;" +
        "box-shadow:0 4px 16px rgba(0,0,0,0.4);transition:opacity 0.3s ease;";
      document.documentElement.appendChild(el);
      setTimeout(() => { el.style.opacity = "0"; }, ok ? 1900 : 4700);
      setTimeout(() => el.remove(), ok ? 2200 : 5000);
    },
    args: [ok, text],
  }).catch(() => { /* restricted page — badge still shows the job */ });
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "fg-grab",
      title: "Grab video with FootageGrab",
      contexts: ["page", "link", "video"],
    });
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "fg-grab") return;
  const url = pickGrabUrl(info, tab);
  const name = await maybeAskName(tab?.id);
  if (name === null) return; // user cancelled the prompt
  grabUrl(url, "context_menu", tab?.id, name);
});

chrome.commands.onCommand.addListener(async command => {
  if (command !== "grab-page") return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !/^https?:\/\//i.test(tab.url)) return;
  const name = await maybeAskName(tab.id);
  if (name === null) return;
  grabUrl(tab.url, "shortcut", tab.id, name);
});

function updateBadge() {
  const active = [...jobs.values()]
    .filter(j => j.state === "queued" || j.state === "running").length;
  const failed = [...jobs.values()].filter(j => j.state === "failed").length;
  chrome.action.setBadgeText({ text: active ? String(active) : (failed ? "!" : "") });
  chrome.action.setBadgeBackgroundColor({ color: failed && !active ? "#f31260" : "#17c964" });
}

chrome.runtime.onMessage.addListener((req, sender, sendResponse) => {
  if (!req || !req.cmd) return;
  if (req.cmd === "host") {
    hostRequest(req.msg, req.timeoutMs || DEFAULT_TIMEOUT_MS)
      .then(sendResponse)
      .catch(e => sendResponse({ ok: false, error: e.message }));
    return true; // async response
  }
  if (req.cmd === "jobs_mirror") {
    sendResponse({ ok: true, jobs: [...jobs.values()] });
  }
});
