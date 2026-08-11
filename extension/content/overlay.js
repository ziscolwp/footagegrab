// The pill: FootageGrab's only permanent chrome on the player.
// Shows In/Out/duration as a timecode readout, Grab/Full actions, help, clear.
(function () {
  "use strict";
  window.FG = window.FG || {};
  const T = window.FG.time;

  let root = null;
  let msgTimer = null;

  const CHEAT_ROWS = [
    ["I", "Set In at playhead"],
    ["O", "Set Out at playhead"],
    ["G", "Grab marked clip(s)"],
    ["⇧G", "Grab full video"],
    ["[ / ]", "Nudge In by 0.25s"],
    ["⇧[ / ⇧]", "Nudge Out by 0.25s"],
    ["Esc", "Clear current pair"],
  ];

  function mount(playerEl) {
    unmount();
    root = document.createElement("div");
    root.className = "fg-pill";
    root.innerHTML = `
      <span class="fg-logo" title="FootageGrab">FG</span>
      <button class="fg-chip" data-act="in" title="Set In at playhead (I)">In</button>
      <button class="fg-chip" data-act="out" title="Set Out at playhead (O)">Out</button>
      <span class="fg-readout" title="Marked range"></span>
      <button class="fg-btn fg-btn-grab" data-act="grab" title="Grab marked clips (G)">Grab</button>
      <button class="fg-btn fg-btn-ghost" data-act="full" title="Grab full video (Shift+G)">Full</button>
      <button class="fg-btn fg-btn-icon" data-act="clear" title="Clear all markers">✕</button>
      <button class="fg-btn fg-btn-icon" data-act="help" title="Keyboard shortcuts">?</button>
      <div class="fg-cheat" hidden></div>
      <div class="fg-msg" hidden></div>`;
    const cheat = root.querySelector(".fg-cheat");
    cheat.innerHTML = CHEAT_ROWS.map(([k, d]) =>
      `<div class="fg-cheat-row"><kbd>${k}</kbd><span>${d}</span></div>`).join("");
    root.addEventListener("click", onClick);
    playerEl.appendChild(root);
    window.FG.state.on(update);
    update(window.FG.state.get());
  }

  function unmount() {
    window.FG.state.off(update);
    root?.remove();
    root = null;
  }

  function onClick(e) {
    const btn = e.target.closest("[data-act]");
    if (!btn || !window.FG.actions) return;
    e.stopPropagation();
    const act = btn.dataset.act;
    if (act === "in") window.FG.actions.setIn();
    else if (act === "out") window.FG.actions.setOut();
    else if (act === "grab") window.FG.actions.grab();
    else if (act === "full") window.FG.actions.grabFull();
    else if (act === "clear") { window.FG.state.clearAll(); flash("Markers cleared"); }
    else if (act === "help") root.querySelector(".fg-cheat").hidden = !root.querySelector(".fg-cheat").hidden;
  }

  function update(state) {
    if (!root) return;
    const d = state.draft;
    const inBtn = root.querySelector('[data-act="in"]');
    const outBtn = root.querySelector('[data-act="out"]');
    const readout = root.querySelector(".fg-readout");
    const grabBtn = root.querySelector('[data-act="grab"]');
    const clearBtn = root.querySelector('[data-act="clear"]');

    inBtn.textContent = d.in != null ? T.fmtClockTenths(d.in) : "In";
    inBtn.classList.toggle("fg-set", d.in != null);
    outBtn.textContent = d.out != null ? T.fmtClockTenths(d.out) : "Out";
    outBtn.classList.toggle("fg-set", d.out != null);

    const staged = state.pairs.length;
    if (d.in != null && d.out != null) {
      readout.textContent = T.fmtDuration(d.out - d.in) + (staged ? ` +${staged}` : "");
      readout.hidden = false;
    } else if (staged) {
      readout.textContent = `${staged} staged`;
      readout.hidden = false;
    } else {
      readout.hidden = true;
    }

    const total = staged + (d.in != null && d.out != null ? 1 : 0);
    grabBtn.textContent = total > 1 ? `Grab ${total}` : "Grab";
    grabBtn.disabled = total === 0;
    clearBtn.hidden = total === 0 && d.in == null && d.out == null;
  }

  function flash(text, isError = false) {
    if (!root) return;
    const msg = root.querySelector(".fg-msg");
    msg.textContent = text;
    msg.classList.toggle("fg-msg-error", isError);
    msg.hidden = false;
    root.classList.remove("fg-shake");
    if (isError) {
      void root.offsetWidth; // restart the shake animation
      root.classList.add("fg-shake");
    }
    clearTimeout(msgTimer);
    msgTimer = setTimeout(() => { msg.hidden = true; }, 2600);
  }

  function coachOnce(playerEl) {
    chrome.storage.local.get("fg_coached").then(({ fg_coached }) => {
      if (fg_coached || !playerEl.isConnected) return;
      const card = document.createElement("div");
      card.className = "fg-coach";
      card.innerHTML = `
        <div class="fg-coach-title">Grab footage without leaving the player</div>
        <div class="fg-coach-body">Press <kbd>I</kbd> to mark In, <kbd>O</kbd> to mark Out,
        then <kbd>G</kbd> — the clip downloads to your footage folder while you keep watching.</div>
        <button class="fg-btn fg-btn-grab">Got it</button>`;
      card.querySelector("button").addEventListener("click", () => {
        card.remove();
        chrome.storage.local.set({ fg_coached: true });
      });
      playerEl.appendChild(card);
      setTimeout(() => card.remove(), 30000);
    }).catch(() => {});
  }

  window.FG.overlay = { mount, unmount, flash, coachOnce };
})();
