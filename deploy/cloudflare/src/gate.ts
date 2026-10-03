// /web/mcp（Web アプリ用の入口）で、コンテナへ通してよい MCP メッセージかを判定する。
// 外部ホスト用の /s/<SECRET_PATH>/mcp には使わない（docs/DESIGN_WEB.md 4.2）。
//
// これは認証ではない。ブラウザ以外からは何でも送れるので、濫用は回数制限で抑える（同 7章）。
// ここでやるのは、Web に出さないと決めたもの（run_sql など）を確実に止めることだけ。

// Web から呼べるツール。run_sql は出さない（DESIGN_WEB.md 5.3）
export const WEB_TOOLS: ReadonlySet<string> = new Set([
  "seikatsu_dashboard",
  "aggregate",
  "accident_map",
  "list_values",
]);

// Web アプリ（と AppBridge 経由のビュー）が使うメソッドだけ
const METHODS: ReadonlySet<string> = new Set([
  "initialize",
  "ping",
  "tools/list",
  "tools/call",
  "resources/read",
]);

const VIEW_URI_PREFIX = "ui://npa-traffic-accident/";

// 1リクエストの上限。ツールの引数は数百バイトしかない
export const MAX_BODY_BYTES = 64 * 1024;

export type Verdict = { ok: true } | { ok: false; id: unknown; reason: string };

interface Message {
  id?: unknown;
  method?: unknown;
  params?: { name?: unknown; uri?: unknown };
}

function check(m: unknown): Verdict {
  if (typeof m !== "object" || m === null) return { ok: false, id: null, reason: "JSON-RPC のメッセージではない" };
  const { id = null, method, params } = m as Message;
  // 応答（サーバーからの要求への返事）は method を持たない
  if (method === undefined) return { ok: true };
  if (typeof method !== "string") return { ok: false, id, reason: "method が文字列でない" };
  if (method.startsWith("notifications/")) return { ok: true };
  if (!METHODS.has(method)) return { ok: false, id, reason: `${method} は Web からは使えない` };
  if (method === "tools/call") {
    const name = params?.name;
    if (typeof name !== "string" || !WEB_TOOLS.has(name)) {
      return { ok: false, id, reason: `ツール ${String(name)} は Web からは使えない` };
    }
  }
  if (method === "resources/read") {
    const uri = params?.uri;
    if (typeof uri !== "string" || !uri.startsWith(VIEW_URI_PREFIX)) {
      return { ok: false, id, reason: `リソース ${String(uri)} は Web からは読めない` };
    }
  }
  return { ok: true };
}

/** POST の本文（JSON 文字列）を判定する。配列（バッチ）なら1つでも駄目なら全体を断る */
export function checkBody(body: string): Verdict {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return { ok: false, id: null, reason: "JSON として読めない" };
  }
  for (const m of Array.isArray(parsed) ? parsed : [parsed]) {
    const v = check(m);
    if (!v.ok) return v;
  }
  return { ok: true };
}

/**
 * 同じオリジンのページからの要求か。ブラウザは fetch に Sec-Fetch-Site を付け、
 * POST には Origin も付ける。どちらかが別オリジンを示していたら断る。
 */
export function sameOrigin(headers: Headers, origin: string): boolean {
  const site = headers.get("Sec-Fetch-Site");
  if (site !== null && site !== "same-origin") return false;
  const o = headers.get("Origin");
  return o === null || o === origin;
}
