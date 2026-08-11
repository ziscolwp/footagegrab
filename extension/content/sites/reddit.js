// Reddit adapter.
// SEL (captured 2026-08 — fix here when Reddit redesigns):
//   new reddit  shreddit-player / shreddit-player-2 custom elements, permalink
//               from the closest <shreddit-post permalink="..."> attribute
//   old reddit  .thing[data-permalink] video, permalink from data-permalink
// v.redd.it media needs the *post* URL — yt-dlp muxes audio from the comments
// page, never from the bare video URL.
(function () {
  "use strict";
  FG.sites.register({
    name: "reddit",
    matches: loc => /(^|\.)reddit\.com$/.test(loc.hostname),
    findVideoContainers: root => {
      const found = [...root.querySelectorAll("shreddit-player, shreddit-player-2")];
      for (const v of root.querySelectorAll(".thing[data-permalink] video")) {
        found.push(v);
      }
      return found;
    },
    resolveUrl: container => {
      let permalink = null;
      const post = container.closest("shreddit-post");
      if (post) permalink = post.getAttribute("permalink");
      if (!permalink) {
        const thing = container.closest(".thing[data-permalink]");
        if (thing) permalink = thing.getAttribute("data-permalink");
      }
      return FG.resolve.redditPermalink(permalink, location.href);
    },
  });
})();
