// Pure permalink resolution for the site adapters — no DOM access, testable
// with `node --test`. Adapters scrape candidate hrefs and hand them here.
// Queries/hashes are always stripped: they are tracking params on every one
// of these sites, and yt-dlp only needs the canonical post URL.
(function (root) {
  "use strict";

  function absolutize(href, baseUrl) {
    if (!href) return null;
    try {
      return new URL(href, baseUrl).href;
    } catch (e) {
      return null;
    }
  }

  function stripQuery(url) {
    try {
      const u = new URL(url);
      return u.origin + u.pathname;
    } catch (e) {
      return url;
    }
  }

  // X/Twitter: tweet permalink is /<user>/status/<id>. Timeline hrefs also
  // include /status/<id>/photo/1, /video/2, /analytics — trim to the tweet.
  function xPermalink(hrefs, pageUrl) {
    const all = hrefs.concat([pageUrl]);
    for (const href of all) {
      const abs = absolutize(href, pageUrl);
      if (!abs) continue;
      const m = stripQuery(abs).match(/^(https:\/\/[^/]+\/[^/]+\/status\/\d+)/);
      if (m) return m[1];
    }
    return null;
  }

  // Reddit: v.redd.it media needs the *post* URL for audio muxing — prefer
  // the shreddit-post permalink attribute, else a /comments/ page URL.
  function redditPermalink(permalinkAttr, pageUrl) {
    if (permalinkAttr) {
      const abs = absolutize(permalinkAttr, pageUrl);
      if (abs) return stripQuery(abs);
    }
    if (/\/comments\//.test(pageUrl)) return stripQuery(pageUrl);
    return null;
  }

  function tiktokPermalink(hrefs, pageUrl) {
    if (/\/(video|photo)\/\d+/.test(pageUrl)) return stripQuery(pageUrl);
    for (const href of hrefs) {
      const abs = absolutize(href, pageUrl);
      if (abs && /\/video\/\d+/.test(abs)) return stripQuery(abs);
    }
    return null;
  }

  function instagramPermalink(hrefs, pageUrl) {
    const isPost = url => /\/(reel|reels|p)\/[^/]+/.test(url);
    if (isPost(pageUrl)) return stripQuery(pageUrl);
    for (const href of hrefs) {
      const abs = absolutize(href, pageUrl);
      if (abs && isPost(abs)) return stripQuery(abs);
    }
    return null;
  }

  const api = { absolutize, xPermalink, redditPermalink, tiktokPermalink, instagramPermalink };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else {
    root.FG = root.FG || {};
    root.FG.resolve = api;
  }
})(this);
