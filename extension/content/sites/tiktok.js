// TikTok adapter.
// SEL (captured 2026-08 — fix here when TikTok redesigns):
//   feed items   [data-e2e="recommend-list-item-container"]
//   video pages  /@user/video/<id> — the URL itself is the permalink; the
//                container is any <video>'s parent (class names are minified)
//   feed link    a[href*="/video/"] inside the item
// yt-dlp fetches the no-watermark stream when available — nothing extra to do.
(function () {
  "use strict";
  FG.sites.register({
    name: "tiktok",
    matches: loc => /(^|\.)tiktok\.com$/.test(loc.hostname),
    findVideoContainers: root => {
      const feed = root.querySelectorAll('[data-e2e="recommend-list-item-container"]');
      if (feed.length) return feed;
      const parents = [];
      for (const v of root.querySelectorAll("video")) {
        if (v.parentElement && !parents.includes(v.parentElement)) parents.push(v.parentElement);
      }
      return parents;
    },
    resolveUrl: container => {
      const hrefs = [];
      for (const a of container.querySelectorAll('a[href*="/video/"]')) {
        hrefs.push(a.getAttribute("href"));
      }
      return FG.resolve.tiktokPermalink(hrefs, location.href);
    },
  });
})();
