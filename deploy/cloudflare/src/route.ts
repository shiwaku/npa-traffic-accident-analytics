// リクエストのパスから、どの入口に回すかを決める。worker.ts から呼ぶ。
//
// Web アプリ（/web/mcp と画面）は WEB_ENABLED が "true" のときだけ開く。
// 回数制限（docs/DESIGN_WEB.md 7.1）が入るまでは閉じておき、外部ホスト用の入口だけを通す。
// 閉じている間も、Web アプリの画面とコードは消さずに配備しておく。

export type Route = "mcp" | "web" | "assets" | "notfound";

export function route(pathname: string, secretPath: string | undefined, webEnabled: boolean): Route {
  const prefix = secretPath ? `/s/${secretPath}` : "";
  if (pathname === `${prefix}/mcp`) return "mcp";
  if (!webEnabled) return "notfound";
  if (pathname === "/web/mcp") return "web";
  return "assets";
}
