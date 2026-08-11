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
      reject(new Error("Native host not installed — run install/install.sh and restart the browser"));
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
    const tabs = await chrome.tabs.query({ url: "https://www.youtube.com/*" });
    await Promise.allSettled(tabs.map(t => chrome.tabs.sendMessage(t.id, payload)));
  } catch (e) { /* no tabs */ }
}

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
