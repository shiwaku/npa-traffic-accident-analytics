// node --experimental-strip-types --test test/route.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { eventOpen, route } from "../src/route.ts";

test("Web を閉じていても、外部ホスト用の入口は通す", () => {
  assert.equal(route("/s/abc/mcp", "abc", false), "mcp");
  assert.equal(route("/mcp", undefined, false), "mcp");
});

test("Web を閉じているときは /web/mcp も画面も 404", () => {
  assert.equal(route("/web/mcp", "abc", false), "notfound");
  assert.equal(route("/", "abc", false), "notfound");
  assert.equal(route("/assets/index.js", "abc", false), "notfound");
});

test("秘密パスがあるときは /mcp を通さない", () => {
  assert.equal(route("/mcp", "abc", false), "notfound");
  assert.equal(route("/mcp", "abc", true), "assets");
});

test("Web を開いているときは /web/mcp と画面を通す", () => {
  assert.equal(route("/web/mcp", "abc", true), "web");
  assert.equal(route("/", "abc", true), "assets");
});

test("発表会用の入口は、EVENT_PATH があれば秘密パスと別に通す", () => {
  assert.equal(route("/e/xyz/mcp", "abc", false, "xyz"), "mcp");
  assert.equal(route("/s/abc/mcp", "abc", false, "xyz"), "mcp");
  assert.equal(route("/e/xyz/mcp", "abc", false, undefined), "notfound");
  assert.equal(route("/e/abc/mcp", "abc", false, "xyz"), "notfound");
  assert.equal(route("/s/xyz/mcp", "abc", false, "xyz"), "notfound");
});

test("発表会用の入口は EVENT_UNTIL を過ぎたら閉じる", () => {
  const until = "2026-10-22T23:59:59+09:00";
  assert.equal(eventOpen(until, new Date("2026-10-22T23:59:00+09:00")), true);
  assert.equal(eventOpen(until, new Date("2026-10-23T00:00:00+09:00")), false);
});

test("EVENT_UNTIL が無い・読めないときは閉じる", () => {
  const now = new Date("2026-10-01T00:00:00+09:00");
  assert.equal(eventOpen(undefined, now), false);
  assert.equal(eventOpen("", now), false);
  assert.equal(eventOpen("10月22日", now), false);
});
