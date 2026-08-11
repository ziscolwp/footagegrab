// Marker state: one draft pair being edited + staged pairs, kept per video id
// so navigating away and back restores your marks within the session.
(function () {
  "use strict";
  window.FG = window.FG || {};

  const MIN_GAP = 0.1; // seconds — an Out must sit at least this far after its In

  const listeners = new Set();
  const byVideo = new Map();
  let videoId = null;
  let current = blank();

  function blank() {
    return { draft: { in: null, out: null }, pairs: [] };
  }

  function emit() {
    for (const fn of listeners) {
      try { fn(get()); } catch (e) { /* one bad listener never blocks the rest */ }
    }
  }

  function get() {
    return { videoId, draft: { ...current.draft }, pairs: current.pairs.map(p => ({ ...p })) };
  }

  function setVideo(id) {
    if (videoId === id) return;
    if (videoId) byVideo.set(videoId, current);
    videoId = id;
    current = (id && byVideo.get(id)) || blank();
    emit();
  }

  function setIn(t) {
    const d = current.draft;
    if (d.in != null && d.out != null) {
      current.pairs.push({ ...d }); // start a new pair, keep the finished one staged
      current.draft = { in: t, out: null };
    } else {
      d.in = t;
      if (d.out != null && d.out <= t + MIN_GAP) d.out = null;
    }
    emit();
    return { ok: true };
  }

  function setOut(t) {
    const d = current.draft;
    if (d.in == null) return { error: "no-in" };
    if (t <= d.in + MIN_GAP) return { error: "order" };
    d.out = t;
    emit();
    return { ok: true };
  }

  function nudge(edge, delta, duration) {
    const d = current.draft;
    if (edge === "in" && d.in != null) {
      const max = (d.out != null ? d.out - MIN_GAP : duration - MIN_GAP);
      d.in = Math.min(Math.max(0, d.in + delta), max);
    } else if (edge === "out" && d.out != null) {
      d.out = Math.min(Math.max(d.in + MIN_GAP, d.out + delta), duration);
    } else {
      return { error: "nothing-to-nudge" };
    }
    emit();
    return { ok: true };
  }

  // pairIndex -1 addresses the draft; >= 0 addresses a staged pair.
  function setEdge(pairIndex, edge, t, duration) {
    const pair = pairIndex === -1 ? current.draft : current.pairs[pairIndex];
    if (!pair) return;
    if (edge === "in") {
      const max = (pair.out != null ? pair.out - MIN_GAP : duration - MIN_GAP);
      pair.in = Math.min(Math.max(0, t), max);
    } else {
      pair.out = Math.min(Math.max((pair.in ?? 0) + MIN_GAP, t), duration);
    }
    emit();
  }

  function grabbable() {
    const out = current.pairs.map(p => ({ ...p }));
    if (current.draft.in != null && current.draft.out != null) out.push({ ...current.draft });
    return out;
  }

  function clearDraft() {
    const had = current.draft.in != null || current.draft.out != null;
    current.draft = { in: null, out: null };
    if (had) emit();
    return had;
  }

  function clearAll() {
    current = blank();
    if (videoId) byVideo.set(videoId, current);
    emit();
  }

  window.FG.state = {
    on: fn => listeners.add(fn),
    off: fn => listeners.delete(fn),
    get, setVideo, setIn, setOut, nudge, setEdge, grabbable, clearDraft, clearAll,
  };
})();
