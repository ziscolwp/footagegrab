// Time formatting shared by the overlay, markers, and toasts.
// Classic script (content scripts can't use ES modules); exports for node tests.
(function () {
  "use strict";

  function fmtClock(seconds) {
    seconds = Math.max(0, Math.floor(seconds || 0));
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function fmtClockTenths(seconds) {
    seconds = Math.max(0, seconds || 0);
    const tenths = Math.floor((seconds % 1) * 10);
    return `${fmtClock(seconds)}.${tenths}`;
  }

  function fmtDuration(seconds) {
    seconds = Math.max(0, seconds || 0);
    if (seconds < 60) return `${(Math.round(seconds * 10) / 10)}s`;
    return fmtClock(seconds);
  }

  const api = { fmtClock, fmtClockTenths, fmtDuration };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") {
    window.FG = window.FG || {};
    window.FG.time = api;
  }
})();
