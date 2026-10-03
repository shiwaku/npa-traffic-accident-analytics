// 自前の MCP ホスト。claude.ai がやっていることを最小限だけ自分でやる。
//
//   1. /web/mcp に MCP クライアントで繋ぐ
//   2. ツールを呼び、そのツールの ui:// リソース（ビューの HTML）を読む
//   3. HTML をサンドボックス iframe に入れ、AppBridge で結果を渡す
//
// ビューからの再問い合わせ（callServerTool）は、AppBridge に渡したクライアントが
// そのまま /web/mcp へ中継する。どのツールを呼べるかは Worker 側が正（DESIGN_WEB.md 5.3）。
import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";
import type { CallToolResult, Tool } from "@modelcontextprotocol/client";
import {
  AppBridge,
  PostMessageTransport,
  RESOURCE_MIME_TYPE,
  getToolUiResourceUri,
  type McpUiDisplayMode,
  type McpUiHostContext,
  type McpUiResourceCsp,
} from "@modelcontextprotocol/ext-apps/app-bridge";

const HOST_INFO = { name: "npa-traffic-accident-web", version: "0.1.0" };

export interface Session {
  client: Client;
  tools: Map<string, Tool>;
  instructions: string | undefined;
}

// MCP Apps に対応していると initialize で名乗る。名乗らないとサーバーは
// 「このクライアントは描画できない」前提の注記を結果に足す（server.py の client_supports_apps）。
// キーは ext-apps の EXTENSION_ID。server エクスポートはブラウザに要らないので値だけ書く
const UI_EXTENSION_ID = "io.modelcontextprotocol/ui";

export async function connect(endpoint = "/web/mcp"): Promise<Session> {
  const client = new Client(HOST_INFO, {
    capabilities: {
      extensions: { [UI_EXTENSION_ID]: { mimeTypes: [RESOURCE_MIME_TYPE] } },
    },
  });
  await client.connect(new StreamableHTTPClientTransport(new URL(endpoint, location.href)));
  const { tools } = await client.listTools();
  return {
    client,
    tools: new Map(tools.map((t) => [t.name, t])),
    instructions: client.getInstructions(),
  };
}

// ビューの HTML は呼ぶたびに読まない。同じセッションの中では変わらないため
const htmlCache = new Map<string, Promise<{ html: string; csp?: McpUiResourceCsp }>>();

function readView(client: Client, uri: string) {
  let p = htmlCache.get(uri);
  if (!p) {
    p = client.readResource({ uri }).then((r) => {
      const c = r.contents[0];
      if (!c || !("text" in c)) throw new Error(`${uri} が HTML を返さなかった`);
      const ui = (c._meta as { ui?: { csp?: McpUiResourceCsp } } | undefined)?.ui;
      return { html: c.text, csp: ui?.csp };
    });
    p.catch(() => htmlCache.delete(uri));
    htmlCache.set(uri, p);
  }
  return p;
}

// _meta.ui.csp を CSP の meta に直す。宣言の無いドメインへは通信させない（DESIGN.md 6.2）。
// iframe は sandbox="allow-scripts" だけで開くので、ビューは不透明オリジンになり、
// このページの DOM・Cookie には触れない。
export function cspFor(csp: McpUiResourceCsp | undefined): string {
  const res = (csp?.resourceDomains ?? []).join(" ");
  const conn = (csp?.connectDomains ?? []).join(" ");
  const frame = (csp?.frameDomains ?? []).join(" ") || "'none'";
  return [
    "default-src 'none'",
    `script-src 'unsafe-inline' blob: ${res}`,
    `style-src 'unsafe-inline' ${res}`,
    `img-src data: blob: ${res}`,
    `font-src data: ${res}`,
    `media-src data: blob: ${res}`,
    `connect-src ${conn || "'none'"}`,
    // MapLibre は blob: の Worker でタイルを処理する
    "worker-src blob:",
    `frame-src ${frame}`,
    "base-uri 'none'",
  ].join("; ");
}

function withCsp(html: string, csp: McpUiResourceCsp | undefined): string {
  const meta = `<meta http-equiv="Content-Security-Policy" content="${cspFor(csp)}">`;
  // <head> の先頭に入れる。後ろに置くと、それより前のスクリプトに効かない
  return /<head[^>]*>/i.test(html)
    ? html.replace(/<head[^>]*>/i, (m) => m + meta)
    : meta + html;
}

function theme(): "light" | "dark" {
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export interface ViewHandle {
  frame: HTMLIFrameElement;
  result: Promise<CallToolResult>;
  close(): Promise<void>;
}

/**
 * ツールを呼び、そのビューを container の中に描く。
 * ツールにビューが無ければ iframe は作らず、結果だけ返す。
 */
export async function runTool(
  s: Session,
  name: string,
  args: Record<string, unknown>,
  container: HTMLElement,
): Promise<ViewHandle | { frame: null; result: Promise<CallToolResult> }> {
  const tool = s.tools.get(name);
  if (!tool) throw new Error(`ツール ${name} が無い`);
  // ビューの読み込みと集計は並行に走らせる。集計の方が遅い
  const result = s.client.callTool({ name, arguments: args }) as Promise<CallToolResult>;
  const uri = getToolUiResourceUri(tool);
  if (!uri) return { frame: null, result };

  const view = await readView(s.client, uri);

  const frame = document.createElement("iframe");
  frame.className = "view";
  frame.setAttribute("sandbox", "allow-scripts");
  frame.title = tool.title ?? tool.name;
  container.append(frame);

  let displayMode: McpUiDisplayMode = "inline";
  const ctx = (): McpUiHostContext => ({
    theme: theme(),
    displayMode,
    availableDisplayModes: ["inline", "fullscreen"],
    toolInfo: { tool },
    locale: "ja-JP",
    platform: "web",
  });

  const bridge = new AppBridge(
    s.client,
    HOST_INFO,
    { serverTools: {}, serverResources: {}, logging: {} },
    { hostContext: ctx() },
  );
  bridge.onsizechange = ({ height }) => {
    if (height !== undefined && displayMode === "inline") frame.style.height = `${height}px`;
  };
  bridge.onrequestdisplaymode = async ({ mode }) => {
    displayMode = mode === "fullscreen" ? "fullscreen" : "inline";
    frame.classList.toggle("fullscreen", displayMode === "fullscreen");
    void bridge.sendHostContextChange({ displayMode });
    return { mode: displayMode };
  };
  bridge.onloggingmessage = (m) => console.debug(`[${name}]`, m.data);

  const initialized = new Promise<void>((resolve) => {
    bridge.oninitialized = () => resolve();
  });

  const mq = matchMedia("(prefers-color-scheme: dark)");
  const onTheme = () => void bridge.sendHostContextChange({ theme: theme() });
  mq.addEventListener("change", onTheme);

  // 受け口を先に開いてから HTML を入れる。逆だとビューの initialize を取りこぼす
  await bridge.connect(new PostMessageTransport(frame.contentWindow!, frame.contentWindow!));
  frame.srcdoc = withCsp(view.html, view.csp);

  await initialized;
  await bridge.sendToolInput({ arguments: args });
  result.then(
    (r) => bridge.sendToolResult(r),
    (e) => bridge.sendToolCancelled({ reason: e instanceof Error ? e.message : String(e) }),
  );

  return {
    frame,
    result,
    async close() {
      mq.removeEventListener("change", onTheme);
      try {
        await bridge.teardownResource({});
      } catch {
        /* ビューが先に落ちていても片付けは続ける */
      }
      await bridge.close();
      frame.remove();
    },
  };
}
