// Grab-time naming prompt: a small FG-styled dialog, used on YouTube and the
// adapter sites when "Ask for clip name" is on. Enter grabs (blank = auto
// name), Esc or clicking outside cancels the grab entirely.
(function () {
  "use strict";
  window.FG = window.FG || {};

  let box = null;

  function close() {
    box?.remove();
    box = null;
  }

  // cb(name): trimmed string to proceed ("" = automatic), null = cancel.
  function ask(suggestion, cb) {
    close();
    box = document.createElement("div");
    box.className = "fg-namer";

    const card = document.createElement("div");
    card.className = "fg-namer-card";
    const label = document.createElement("div");
    label.className = "fg-namer-label";
    label.textContent = "Name this clip";
    const input = document.createElement("input");
    input.className = "fg-namer-input";
    input.type = "text";
    input.value = suggestion || "";
    input.placeholder = "Blank = automatic";
    input.spellcheck = false;
    const hint = document.createElement("div");
    hint.className = "fg-namer-hint";
    hint.textContent = "Enter to grab · Esc to cancel";
    card.append(label, input, hint);
    box.appendChild(card);

    const finish = value => { close(); cb(value); };
    input.addEventListener("keydown", e => {
      e.stopPropagation(); // keep site hotkeys (and ours) quiet while typing
      if (e.key === "Enter") finish(input.value.trim());
      else if (e.key === "Escape") finish(null);
    });
    box.addEventListener("mousedown", e => {
      if (e.target === box) finish(null);
    });

    document.body.appendChild(box);
    input.focus();
    // select all (one keystroke replaces the suggestion) but anchor the view
    // at the START of the title — plain select() scrolls to the end
    input.setSelectionRange(0, input.value.length, "backward");
    input.scrollLeft = 0;
  }

  window.FG.namer = { ask };
})();
