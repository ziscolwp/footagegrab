// Keyboard layer. Capture-phase so I/O/G reach us before YouTube's own bindings
// (this intentionally overrides YouTube's "i" miniplayer shortcut on watch pages).
(function () {
  "use strict";
  window.FG = window.FG || {};

  const NUDGE = 0.25; // seconds

  function editable(el) {
    return el && (el.isContentEditable ||
      /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) ||
      el.closest?.("#contenteditable-root"));
  }

  function onKeyDown(e) {
    const A = window.FG.actions;
    if (!A || !A.ready()) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (editable(e.target) || editable(document.activeElement)) return;

    let acted = false;
    switch (e.code) {
      case "KeyI":
        if (!e.shiftKey) { A.setIn(); acted = true; }
        break;
      case "KeyO":
        if (!e.shiftKey) { A.setOut(); acted = true; }
        break;
      case "KeyG":
        if (e.shiftKey) A.grabFull(); else A.grab();
        acted = true;
        break;
      case "BracketLeft":
        A.nudge(e.shiftKey ? "out" : "in", -NUDGE);
        acted = true;
        break;
      case "BracketRight":
        A.nudge(e.shiftKey ? "out" : "in", +NUDGE);
        acted = true;
        break;
      case "Escape":
        // Only consume Esc when there is a draft to clear; otherwise let
        // YouTube use it (e.g. to exit fullscreen).
        acted = window.FG.state.clearDraft();
        if (acted) window.FG.overlay.flash("Pair cleared");
        break;
    }
    if (acted) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }

  function install() {
    window.addEventListener("keydown", onKeyDown, true);
  }

  window.FG.hotkeys = { install };
})();
