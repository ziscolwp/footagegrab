// Instagram adapter.
// SEL (captured 2026-08 — fix here when Instagram redesigns):
//   containers  article video (feed) and bare <video> (reel pages) — parents
//               get the button since <video> renders no children
//   permalink   /reel/<id>/ or /p/<id>/ from the page URL, else the closest
//               article's a[href*="/reel/"] / a[href*="/p/"] timestamp link
// Most Instagram media requires login: expect the "enable Browser cookies"
// hint from the host on the first failed grab.
(function () {
  "use strict";
  FG.sites.register({
    name: "instagram",
    matches: loc => /(^|\.)instagram\.com$/.test(loc.hostname),
    findVideoContainers: root => {
      const parents = [];
      for (const v of root.querySelectorAll("video")) {
        if (v.parentElement && !parents.includes(v.parentElement)) parents.push(v.parentElement);
      }
      return parents;
    },
    resolveUrl: container => {
      const article = container.closest("article");
      const hrefs = [];
      if (article) {
        for (const a of article.querySelectorAll('a[href*="/reel/"], a[href*="/p/"]')) {
          hrefs.push(a.getAttribute("href"));
        }
      }
      return FG.resolve.instagramPermalink(hrefs, location.href);
    },
  });
})();
