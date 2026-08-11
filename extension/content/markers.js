// In/Out flags and the gradient selection band on YouTube's progress bar.
// Handles are draggable; staged pairs render dimmer than the active draft.
(function () {
  "use strict";
  window.FG = window.FG || {};

  let layer = null;
  let barEl = null;
  let videoEl = null;
  let dragging = null; // { pairIndex, edge }
  let rafPending = false;

  function mount(bar, video) {
    unmount();
    barEl = bar;
    videoEl = video;
    layer = document.createElement("div");
    layer.className = "fg-marker-layer";
    layer.addEventListener("mousedown", onMouseDown, true);
    barEl.appendChild(layer);
    window.FG.state.on(render);
    render(window.FG.state.get());
  }

  function unmount() {
    window.FG.state.off(render);
    layer?.remove();
    layer = null;
    barEl = null;
    videoEl = null;
    dragging = null;
  }

  function duration() {
    const d = videoEl?.duration;
    return (Number.isFinite(d) && d > 0) ? d : 0;
  }

  function pct(t) {
    const d = duration();
    return d ? Math.min(100, Math.max(0, (t / d) * 100)) : 0;
  }

  function render(state) {
    if (!layer) return;
    layer.textContent = "";
    state.pairs.forEach((pair, i) => renderPair(pair, i, false));
    renderPair(state.draft, -1, true);
  }

  function renderPair(pair, index, isDraft) {
    if (pair.in == null && pair.out == null) return;
    const cls = isDraft ? "fg-draft" : "fg-staged";
    if (pair.in != null && pair.out != null) {
      const fill = document.createElement("div");
      fill.className = `fg-range ${cls}`;
      fill.style.left = `${pct(pair.in)}%`;
      fill.style.width = `${Math.max(0.2, pct(pair.out) - pct(pair.in))}%`;
      layer.appendChild(fill);
    }
    if (pair.in != null) layer.appendChild(handle("in", pair.in, index, cls));
    if (pair.out != null) layer.appendChild(handle("out", pair.out, index, cls));
  }

  function handle(edge, t, pairIndex, cls) {
    const el = document.createElement("div");
    el.className = `fg-handle fg-handle-${edge} ${cls}`;
    el.style.left = `${pct(t)}%`;
    el.dataset.edge = edge;
    el.dataset.pair = String(pairIndex);
    el.title = edge === "in" ? "In — drag to adjust" : "Out — drag to adjust";
    return el;
  }

  function onMouseDown(e) {
    const h = e.target.closest?.(".fg-handle");
    if (!h) return; // clicks elsewhere fall through to YouTube's seek
    e.preventDefault();
    e.stopPropagation();
    dragging = { pairIndex: Number(h.dataset.pair), edge: h.dataset.edge };
    document.body.classList.add("fg-dragging");
    window.addEventListener("mousemove", onMouseMove, true);
    window.addEventListener("mouseup", onMouseUp, true);
  }

  function onMouseMove(e) {
    if (!dragging || rafPending) return;
    rafPending = true;
    const x = e.clientX;
    requestAnimationFrame(() => {
      rafPending = false;
      if (!dragging || !barEl) return;
      const rect = barEl.getBoundingClientRect();
      const frac = Math.min(1, Math.max(0, (x - rect.left) / rect.width));
      window.FG.state.setEdge(dragging.pairIndex, dragging.edge, frac * duration(), duration());
    });
  }

  function onMouseUp() {
    dragging = null;
    document.body.classList.remove("fg-dragging");
    window.removeEventListener("mousemove", onMouseMove, true);
    window.removeEventListener("mouseup", onMouseUp, true);
  }

  window.FG.markers = { mount, unmount };
})();
