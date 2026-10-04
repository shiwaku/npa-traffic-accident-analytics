// node --experimental-strip-types --test test/route.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { route } from "../src/route.ts";

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
