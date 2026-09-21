// claude.ai → この Worker → コンテナ(server.py --http) → R2 の parquet
//
// Worker は転送だけ。MCP のセッションはコンテナのメモリ上にあるので、
// インスタンス名を固定して常に同じコンテナに送る。
import { Container, getContainer } from "@cloudflare/containers";

export class McpContainer extends Container {
  defaultPort = 8080;
  // 最後のリクエストからこの時間で寝る。寝ている間は課金されず、次のリクエストで起きる。
  sleepAfter = "10m";
}

interface Env {
  MCP_CONTAINER: DurableObjectNamespace<McpContainer>;
  // 設定すると /s/<SECRET_PATH>/mcp 以外を 404 にする(自分だけで使う場合の簡易認証)。
  // wrangler secret put SECRET_PATH で入れる。未設定なら /mcp をそのまま通す。
  SECRET_PATH?: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const prefix = env.SECRET_PATH ? `/s/${env.SECRET_PATH}` : "";
    if (url.pathname !== `${prefix}/mcp`) {
      return new Response("Not found", { status: 404 });
    }
    url.pathname = "/mcp";
    const container = getContainer(env.MCP_CONTAINER, "main");
    return container.fetch(new Request(url, request));
  },
};
