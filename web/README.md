# web/ — 自前の MCP ホスト

[docs/DESIGN_WEB.md](../docs/DESIGN_WEB.md) の Web アプリ。claude.ai と同じやり方で
MCP サーバーに繋ぎ、`ui://` のビュー（`mcp_server/app/`）を iframe に描く。

いまは段階A（同 9章）。引数を固定した3つのボタン（ダッシュボード・集計表・地図）だけがある。
フォームは段階B、チャットは段階Cで足す。

| ファイル | 役割 |
|---|---|
| `src/host.ts` | MCP クライアント（`/web/mcp`）と、ビューの描画（`AppBridge` + サンドボックス iframe） |
| `src/main.ts` | 画面。いまは固定引数のボタンだけ |
| `vite.config.ts` | 手元では `/web/mcp` を `server.py` へ中継する |

## 手元で動かす

```bash
python mcp_server/server.py --http --port 8000 --allow-host '*'
cd web && npm install && npm run dev        # http://localhost:5173/
```

`--allow-host '*'` が要る。無いとブラウザの `Origin`（`http://localhost:5173`）が
`server.py` の DNS リバインディング対策に弾かれて 403 になる。本番のコンテナも同じ指定で動いている
（`deploy/cloudflare/Dockerfile`）。

本番では Worker が `web/dist` を配り、`/web/mcp` をコンテナへ通す（`deploy/cloudflare/`）。
ビルドは `npm run build`。

## ビューとのつなぎ方で決めたこと

- **ビューの HTML は実行時に `resources/read` で取る。** `mcp_server/app/dist` をコピーしない。
  ビューを直したとき、こちらの再ビルドが要らない
- **initialize で MCP Apps 対応を名乗る**（`extensions["io.modelcontextprotocol/ui"]`）。
  名乗らないと `server.py` が「このクライアントは描画できない」前提の注記を結果に足す
- **iframe は `sandbox="allow-scripts"` だけで開く。** ビューは不透明オリジンになり、
  このページの DOM・Cookie に触れない。ビューが宣言した `_meta.ui.csp` を CSP の `<meta>` にして
  HTML の先頭に差し込む（地図の地理院タイルだけが通る）
- **ビューからの再問い合わせ（`callServerTool`）は `AppBridge` がそのまま `/web/mcp` へ中継する。**
  どのツールを呼べるかは Worker の `src/gate.ts` が正

## 確かめたこと（2026-10-03、ローカルの server.py + ヘッドレス Chrome）

| | 結果 |
|---|---|
| ダッシュボード（全国・strict） | 描画。期間合計 355,708件 |
| ビュー内の strict → broad 切り替え | `callServerTool` が中継され 639,132件（CLAUDE.md の値と一致） |
| 集計表（年別） | 描画。7行・2,182,298件 |
| 地図（東京都・strict、約1.5 MB のビュー） | 描画。地理院タイルも CSP を通って読める |

Python の `mcp` クライアントで読めなかった地図ビュー（`deploy/cloudflare/README.md` の落とし穴）も、
ブラウザの `@modelcontextprotocol/client` では読めた。
