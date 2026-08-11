// Thin messaging layer between popup and the background worker.

export function send(cmd, extra = {}) {
  return chrome.runtime.sendMessage({ cmd, ...extra });
}

export function host(msg, timeoutMs) {
  return send("host", { msg, timeoutMs });
}

export function jobsMirror() {
  return send("jobs_mirror");
}

export function fmtClock(seconds) {
  seconds = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}
