// node --test extension/tests/resolve.test.js
// Pure permalink resolution for the site adapters. Href fixtures mirror what
// the adapters scrape from live DOMs (captured 2026-08).
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const R = require("../content/sites/resolve.js");

// ---- X / Twitter ----------------------------------------------------------

test("x: picks the status permalink from tweet hrefs", () => {
  const hrefs = [
    "/theuser",
    "/theuser/status/1815551234567890123/analytics",
    "/theuser/status/1815551234567890123",
    "/hashtag/blender",
  ];
  assert.strictEqual(
    R.xPermalink(hrefs, "https://x.com/home"),
    "https://x.com/theuser/status/1815551234567890123"
  );
});

test("x: strips /photo/1 and /video/1 suffixes and tracking queries", () => {
  assert.strictEqual(
    R.xPermalink(["/u/status/99/photo/1?s=20"], "https://x.com/home"),
    "https://x.com/u/status/99"
  );
  assert.strictEqual(
    R.xPermalink(["/u/status/99/video/2"], "https://twitter.com/home"),
    "https://twitter.com/u/status/99"
  );
});

test("x: falls back to the page URL on a status page", () => {
  assert.strictEqual(
    R.xPermalink([], "https://x.com/u/status/42?s=20"),
    "https://x.com/u/status/42"
  );
});

test("x: timeline page with no status hrefs resolves to null", () => {
  assert.strictEqual(R.xPermalink(["/explore"], "https://x.com/home"), null);
});

// ---- Reddit ---------------------------------------------------------------

test("reddit: shreddit permalink attribute wins", () => {
  assert.strictEqual(
    R.redditPermalink("/r/videos/comments/abc123/cool_video/", "https://www.reddit.com/r/videos/"),
    "https://www.reddit.com/r/videos/comments/abc123/cool_video/"
  );
});

test("reddit: falls back to the page URL on a comments page", () => {
  assert.strictEqual(
    R.redditPermalink(null, "https://old.reddit.com/r/aww/comments/xyz/title/?share_id=1"),
    "https://old.reddit.com/r/aww/comments/xyz/title/"
  );
});

test("reddit: feed page without a permalink resolves to null", () => {
  assert.strictEqual(R.redditPermalink("", "https://www.reddit.com/r/videos/"), null);
});

// ---- TikTok ---------------------------------------------------------------

test("tiktok: video page resolves to the page URL, query stripped", () => {
  assert.strictEqual(
    R.tiktokPermalink([], "https://www.tiktok.com/@user/video/7300000000000000000?is_from_webapp=1"),
    "https://www.tiktok.com/@user/video/7300000000000000000"
  );
});

test("tiktok: feed item resolves via its /video/ href", () => {
  const hrefs = ["/@user", "https://www.tiktok.com/@user/video/7311111111111111111"];
  assert.strictEqual(
    R.tiktokPermalink(hrefs, "https://www.tiktok.com/foryou"),
    "https://www.tiktok.com/@user/video/7311111111111111111"
  );
});

test("tiktok: nothing video-like resolves to null", () => {
  assert.strictEqual(R.tiktokPermalink(["/@user"], "https://www.tiktok.com/foryou"), null);
});

// ---- Instagram ------------------------------------------------------------

test("instagram: reel page resolves to the page URL, tracking stripped", () => {
  assert.strictEqual(
    R.instagramPermalink([], "https://www.instagram.com/reel/Cx1yz/?igsh=abc"),
    "https://www.instagram.com/reel/Cx1yz/"
  );
});

test("instagram: feed post resolves via /p/ or /reel/ href", () => {
  assert.strictEqual(
    R.instagramPermalink(["/user/", "/p/Cabcdef/"], "https://www.instagram.com/"),
    "https://www.instagram.com/p/Cabcdef/"
  );
  assert.strictEqual(
    R.instagramPermalink(["/reel/Czzz/"], "https://www.instagram.com/"),
    "https://www.instagram.com/reel/Czzz/"
  );
});

test("instagram: profile page with no post hrefs resolves to null", () => {
  assert.strictEqual(R.instagramPermalink(["/user/"], "https://www.instagram.com/user/"), null);
});

// ---- shared ---------------------------------------------------------------

test("absolutize handles relative, protocol-relative, and absolute hrefs", () => {
  assert.strictEqual(R.absolutize("/a/b", "https://x.com/home"), "https://x.com/a/b");
  assert.strictEqual(R.absolutize("https://y.com/z", "https://x.com/"), "https://y.com/z");
  assert.strictEqual(R.absolutize(null, "https://x.com/"), null);
});
