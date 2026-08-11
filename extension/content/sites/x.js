// X / Twitter adapter.
// SEL (captured 2026-08 — fix here when X redesigns):
//   video containers  article [data-testid="videoPlayer"], [data-testid="videoComponent"]
//   tweet permalink   closest <article> → a[href*="/status/"], preferring the
//                     one wrapping a <time> (that's the tweet's own timestamp;
//                     quoted tweets add other /status/ links)
(function () {
  "use strict";
  FG.sites.register({
    name: "x",
    matches: loc => /(^|\.)(x|twitter)\.com$/.test(loc.hostname),
    findVideoContainers: root =>
      root.querySelectorAll('article [data-testid="videoPlayer"], article [data-testid="videoComponent"]'),
    resolveUrl: container => {
      const article = container.closest("article");
      const hrefs = [];
      if (article) {
        const links = article.querySelectorAll('a[href*="/status/"]');
        for (const a of links) if (a.querySelector("time")) hrefs.push(a.getAttribute("href"));
        for (const a of links) hrefs.push(a.getAttribute("href"));
      }
      return FG.resolve.xPermalink(hrefs, location.href);
    },
  });
})();
