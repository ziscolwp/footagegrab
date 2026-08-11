// Orchestrator: waits for YouTube's player, survives SPA navigation, wires
// state -> UI, and turns marks into enqueue messages for the background worker.
(function () {
  "use strict";
  window.FG = window.FG || {};
  const T = window.FG.time;

  // Every YouTube DOM dependency lives here — when YouTube ships a redesign,
  // this is the list to fix.
  const SEL = {
    player: "#movie_player, .html5-video-player",
    video: "video.html5-main-video, video",
    bar: ".ytp-progress-bar",
    title: "h1.ytd-watch-metadata yt-formatted-string, h1.title yt-formatted-string",
  };

  let player = null;
  let video = null;
  let mounted = false;
  let currentVid = null;
  let hostDownNotified = false;

  function watchId() {
    try {
      const u = new URL(location.href);
      if (u.pathname === "/watch") return u.searchParams.get("v");
    } catch (e) { /* ignore */ }
    return null;
  }

  function videoTitle() {
    const el = document.querySelector(SEL.title);
    const t = el?.textContent?.trim();
    if (t) return t;
    return document.title.replace(/ - YouTube$/, "").trim();
  }

  function teardown() {
    if (!mounted) return;
    window.FG.markers.unmount();
    window.FG.overlay.unmount();
    window.FG.toasts.unmount();
    mounted = false;
    player = null;
    video = null;
  }

  function tryMount(vid) {
    const p = document.querySelector(SEL.player);
    const v = p?.querySelector(SEL.video);
    const bar = p?.querySelector(SEL.bar);
    if (!p || !v || !bar || !Number.isFinite(v.duration) || v.duration <= 0) return false;
    player = p;
    video = v;
    window.FG.markers.mount(bar, v);
    window.FG.overlay.mount(p);
    window.FG.toasts.mount(p);
    window.FG.overlay.coachOnce(p);
    window.FG.state.setVideo(vid);
    mounted = true;
    return true;
  }

  function tick() {
    const vid = watchId();
    if (!vid) {
      if (mounted) teardown();
      currentVid = null;
      return;
    }
    if (vid !== currentVid || !mounted || !player?.isConnected) {
      teardown();
      if (tryMount(vid)) currentVid = vid;
    }
  }

  // -- guards ---------------------------------------------------------------

  function blocked() {
    if (!mounted || !video) return "Player not ready yet";
    if (player.classList.contains("ad-showing") || player.classList.contains("ad-interrupting")) {
      return "Wait for the ad to finish — marks would land on the ad";
    }
    if (!Number.isFinite(video.duration)) {
      return "Live streams can't be grabbed";
    }
    return null;
  }

  // -- actions (used by hotkeys, pill buttons) ------------------------------

  window.FG.actions = {
    ready: () => mounted,

    setIn() {
      const why = blocked();
      if (why) return window.FG.overlay.flash(why, true);
      window.FG.state.setIn(video.currentTime);
    },

    setOut() {
      const why = blocked();
      if (why) return window.FG.overlay.flash(why, true);
      const res = window.FG.state.setOut(video.currentTime);
      if (res.error === "no-in") window.FG.overlay.flash("Set In first — press I", true);
      else if (res.error === "order") window.FG.overlay.flash("Out must be after In", true);
    },

    nudge(edge, delta) {
      if (!mounted) return;
      const res = window.FG.state.nudge(edge, delta, video.duration);
      if (!res.error) {
        const d = window.FG.state.get().draft;
        const t = edge === "in" ? d.in : d.out;
        window.FG.overlay.flash(`${edge === "in" ? "In" : "Out"} ${T.fmtClockTenths(t)}`);
      }
    },

    grab() {
      const why = blocked();
      if (why) return window.FG.overlay.flash(why, true);
      const segments = window.FG.state.grabbable();
      if (!segments.length) {
        const d = window.FG.state.get().draft;
        const hint = d.in != null ? "Set Out first — press O" : "Set In first — press I";
        return window.FG.overlay.flash(hint, true);
      }
      enqueue({ mode: "segments", segments: segments.map(s => ({ start: s.in, end: s.out })) },
        segments.length);
    },

    grabFull() {
      const why = blocked();
      if (why) return window.FG.overlay.flash(why, true);
      enqueue({ mode: "full" }, 0);
    },
  };

  function enqueue(extra, count) {
    const payload = {
      url: `https://www.youtube.com/watch?v=${currentVid}`,
      video_id: currentVid,
      title: videoTitle(),
      ...extra,
    };
    chrome.runtime.sendMessage({ cmd: "host", msg: { type: "enqueue", ...payload } })
      .then(res => {
        if (res?.ok) {
          window.FG.state.clearAll();
          const n = count || 1;
          window.FG.overlay.flash(count ? `${n} clip${n > 1 ? "s" : ""} queued` : "Full video queued");
        } else {
          window.FG.toasts.show("error", res?.error || "Could not reach the download host", {
            actions: [{ label: "Help", fn: () => window.FG.toasts.show("info",
              "Run install.sh, fully restart the browser, then click the FootageGrab toolbar icon to check host status.", { timeout: 12000 }) }],
          });
        }
      })
      .catch(() => {
        window.FG.toasts.show("error",
          "FootageGrab host not reachable — click the toolbar icon for setup help");
      });
  }

  // -- push updates from the background worker ------------------------------

  chrome.runtime.onMessage.addListener((req) => {
    if (!req || !mounted) return;
    if (req.kind === "job_update") {
      window.FG.toasts.upsertJob(req.job);
    } else if (req.kind === "host_down" && !hostDownNotified) {
      hostDownNotified = true;
      setTimeout(() => { hostDownNotified = false; }, 60000);
    }
  });

  // -- boot -----------------------------------------------------------------

  window.FG.hotkeys.install();
  document.addEventListener("yt-navigate-finish", () => setTimeout(tick, 300));
  setInterval(tick, 800); // fallback for navigations that don't fire the event
  tick();
})();
