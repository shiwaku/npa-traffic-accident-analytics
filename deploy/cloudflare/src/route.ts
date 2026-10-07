// リクエストのパスから、どの入口に回すかを決める。worker.ts から呼ぶ。
//
// Web アプリ（/web/mcp と画面）は WEB_ENABLED が "true" のときだけ開く。
// 回数制限（docs/DESIGN_WEB.md 7.1）が入るまでは閉じておき、外部ホスト用の入口だけを通す。
// 閉じている間も、Web アプリの画面とコードは消さずに配備しておく。
//
// 発表会用の入口 /e/<EVENT_PATH>/mcp は、来場者に配る使い捨ての URL（issue #31）。
// SECRET_PATH とは別に持つので、配った URL を止めても自分の登録は生きる。

export type Route = "mcp" | "web" | "assets" | "notfound";

export function route(
  pathname: string,
  secretPath: string | undefined,
  webEnabled: boolean,
  eventPath?: string,
): Route {
  const prefix = secretPath ? `/s/${secretPath}` : "";
  if (pathname === `${prefix}/mcp`) return "mcp";
  if (eventPath && pathname === `/e/${eventPath}/mcp`) return "mcp";
  if (!webEnabled) return "notfound";
  if (pathname === "/web/mcp") return "web";
  return "assets";
}

/**
 * 発表会用の入口を開いてよいか。EVENT_UNTIL（ISO 8601 の日時）を過ぎたら閉じる。
 * secret delete を忘れても止まるように、期限が無い・読めないときも閉じる側に倒す。
 */
export function eventOpen(until: string | undefined, now: Date): boolean {
  if (!until) return false;
  const t = Date.parse(until);
  return !Number.isNaN(t) && now.getTime() <= t;
}
