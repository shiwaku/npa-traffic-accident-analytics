// node --experimental-strip-types --test test/gate.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { checkBody, sameOrigin } from "../src/gate.ts";

const call = (name: string) => JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: {} } });

test("Web に出すツールは通す", () => {
  for (const n of ["seikatsu_dashboard", "aggregate", "accident_map", "list_values"]) {
    assert.deepEqual(checkBody(call(n)), { ok: true });
  }
});

test("run_sql は断る", () => {
  const v = checkBody(call("run_sql"));
  assert.equal(v.ok, false);
  assert.equal(!v.ok && v.id, 1);
});

test("バッチに1つでも駄目なものがあれば全体を断る", () => {
  const b = `[${call("aggregate")},${call("run_sql")}]`;
  assert.equal(checkBody(b).ok, false);
});

test("initialize・通知・応答は通す", () => {
  assert.ok(checkBody(JSON.stringify({ jsonrpc: "2.0", id: 0, method: "initialize", params: {} })).ok);
  assert.ok(checkBody(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" })).ok);
  assert.ok(checkBody(JSON.stringify({ jsonrpc: "2.0", id: 5, result: {} })).ok);
});

test("許可していないメソッドとリソースは断る", () => {
  assert.equal(checkBody(JSON.stringify({ jsonrpc: "2.0", id: 2, method: "prompts/list" })).ok, false);
  const read = (uri: string) => JSON.stringify({ jsonrpc: "2.0", id: 3, method: "resources/read", params: { uri } });
  assert.ok(checkBody(read("ui://npa-traffic-accident/accident-map.html")).ok);
  assert.equal(checkBody(read("file:///etc/passwd")).ok, false);
});

test("JSON でなければ断る", () => {
  assert.equal(checkBody("{").ok, false);
});

test("別オリジンからの要求を断る", () => {
  const o = "https://example.workers.dev";
  assert.ok(sameOrigin(new Headers({ "Sec-Fetch-Site": "same-origin", Origin: o }), o));
  assert.ok(sameOrigin(new Headers({ "Sec-Fetch-Site": "same-origin" }), o));
  assert.equal(sameOrigin(new Headers({ "Sec-Fetch-Site": "cross-site", Origin: "https://evil.example" }), o), false);
  assert.equal(sameOrigin(new Headers({ Origin: "https://evil.example" }), o), false);
});
