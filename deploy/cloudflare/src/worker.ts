// 入口は3つあり、どれも同じコンテナ（server.py --http）に届く（docs/DESIGN_WEB.md 3章）。
//
//   /s/<SECRET_PATH>/mcp  外部の MCP ホスト（claude.ai など）。秘密パスで守る
//   /web/mcp              Web アプリの MCP クライアント。gate.ts で通すものを絞る
//   /・/assets/*          Web アプリ本体（web/dist）。静的アセットとして配る
//
// Web アプリの2つは WEB_ENABLED が "true" のときだけ開く（route.ts）。
//
// Worker は転送だけ。MCP のセッションはコンテナのメモリ上にあるので、
// インスタンス名を固定して常に同じコンテナに送る。
import { Container, getContainer } from "@cloudflare/containers";
import { MAX_BODY_BYTES, checkBody, sameOrigin } from "./gate";
import { route } from "./route";

export class McpContainer extends Container {
  defaultPort = 8080;
  // 最後のリクエストからこの時間で寝る。寝ている間は課金されず、次のリクエストで起きる。
  sleepAfter = "10m";
}

interface Env {
  MCP_CONTAINER: DurableObjectNamespace<McpContainer>;
  // 設定すると外部ホスト用の入口を /s/<SECRET_PATH>/mcp にする(自分だけで使う場合の簡易認証)。
  // wrangler secret put SECRET_PATH で入れる。未設定なら /mcp をそのまま通す。
  SECRET_PATH?: string;
  // "true" のときだけ Web アプリ（/web/mcp と画面）を開く。wrangler.jsonc の vars で切り替える
  WEB_ENABLED?: string;
  ASSETS: Fetcher;
}

function toContainer(request: Request, env: Env, body?: string): Promise<Response> {
  const url = new URL(request.url);
  url.pathname = "/mcp";
  // 本文を読んだ後は元の Request を使い回せないので、読んだ文字列で作り直す
  const forwarded = body === undefined
    ? new Request(url, request)
    : new Request(url, { method: request.method, headers: request.headers, body });
  return getContainer(env.MCP_CONTAINER, "main").fetch(forwarded);
}

// JSON-RPC のエラーとして断る。HTTP エラーにすると、ビューには
// 「HTTP 403」としか出ず理由が分からないため
function reject(id: unknown, reason: string): Response {
  return Response.json({ jsonrpc: "2.0", id, error: { code: -32601, message: reason } });
}

async function web(request: Request, env: Env): Promise<Response> {
  const origin = new URL(request.url).origin;
  if (!sameOrigin(request.headers, origin)) {
    return new Response("Forbidden", { status: 403 });
  }
  if (request.method !== "POST") {
    // GET（サーバーからの通知の SSE）と DELETE（セッション終了）は中身が無いので素通し
    return toContainer(request, env);
  }
  const body = await request.text();
  if (body.length > MAX_BODY_BYTES) {
    return new Response("Payload Too Large", { status: 413 });
  }
  const v = checkBody(body);
  if (!v.ok) return reject(v.id, v.reason);
  return toContainer(request, env, body);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const { pathname } = new URL(request.url);
    switch (route(pathname, env.SECRET_PATH, env.WEB_ENABLED === "true")) {
      case "mcp": return toContainer(request, env);
      case "web": return web(request, env);
      case "assets": return env.ASSETS.fetch(request);
      default: return new Response("Not found", { status: 404 });
    }
  },
};
