# MCPサーバー

R2 上の GeoParquet を DuckDB で集計する MCP サーバー。
利用者は自分の Claude から日本語で聞くだけでよく、SQL も定義の知識も要らない。

## ツール

| | |
|---|---|
| `seikatsu_dashboard` | 生活道路の概況。**UI付き**（MCP Apps）。全事故を母数として同時に数える |
| `aggregate` | 条件を指定して集計する。細かい切り口はこれ |
| `list_values` | 項目の有効なコード値とラベルと件数を返す |
| `run_sql` | `aggregate` で表現できない集計のための逃げ道。読み取り専用 |

## UI（MCP Apps）

`seikatsu_dashboard` は [MCP Apps 拡張](https://apps.extensions.modelcontextprotocol.io/)
（`io.modelcontextprotocol/ui`）で `ui://` リソースに紐づいており、対応ホストでは
グラフ付きのダッシュボードがサンドボックスiframeで描画される。

| | |
|---|---|
| 描画される | Claude Desktop、claude.ai |
| 描画されない | ターミナルの Claude Code（iframeを持たない）。ツールは同じ数字を返すので集計としては壊れない |

**サーバー側**は `mcp.server.apps`（`mcp>=2.2.0` に同梱、追加依存なし）。
**ビュー側**は `app/` を公式SDK `@modelcontextprotocol/ext-apps` で組み、
Vite で単一HTMLにバンドルしたものを `dashboard.py` が読む。

```bash
cd mcp_server/app && npm install && npm run build   # -> app/dist/mcp-app.html
```

ハンドシェイク（`ui/initialize`）・`tool-result` の受信・`tools/call` の送出・
サイズ通知は SDK の `App` クラスに任せる。**ここを手書きしないこと。**
`ui/initialize` の params は `appInfo` / `appCapabilities` / `protocolVersion` で、
`appInfo` を `clientInfo` と書くとホストによっては黙って描画されない。

`vite-plugin-singlefile` は必須。サンドボックスiframeは外部アセットを取りに
行けないため、JS/CSSがHTMLに畳み込まれていないとビューは動かない。
ビューは外部リソースを一切読まない（グラフはインラインSVG、配色とフォントは
ホストが渡す CSS 変数）ので、`_meta.ui.csp` で追加ドメインを宣言していない。

ビュー内の **strict / broad トグル**は `visibility: ["model","app"]` の同じツールを
`app.callServerTool(...)` で呼び直す。会話に戻らずに定義を切り替えられるので、
**件数が1.79倍動くこと**をその場で確かめられる。

ツールは `CallToolResult` を返し、`content`（モデルが読む表）と
`structuredContent`（ビューが読むデータ）を分けている。分けないと、
ビューが描画されたときに同じ数字が二重に会話へ流れる。

拡張はサーバー構築時に取り込まれるため、`apps.add_html_resource(...)` と
`@apps.tool(...)` は `MCPServer(...)` より**前**に置く必要がある。

なお、この作業には公式スキルがある。迷ったらこれに従う。

```
/plugin marketplace add modelcontextprotocol/ext-apps
/plugin install mcp-apps@mcp-apps          # add-app-to-server ほか
```

## 設計の要点

**引数はラベル文字列ではなくコード値で受け取る。** コード表のラベルは全角ハイフン
マイナス(U+FF0D)と全角チルダ(U+FF5E)を含み、似た別文字を1つ混ぜるとクエリは
エラーにならず0件を返す。`'01','02','11'` のようなASCIIのコードで受けて
サーバー側でラベルに変換すれば、この事故が構造的に起きない。

**1コードが複数ラベルを持つ場合がある。** 当事者種別の `36` は2023年以前が
`二輪車－原付自転車`、2024年以降が `二輪車－一般原付自転車`。`vocab.py` は
2019〜2024の全年次を統合しているので、年次をまたいでも取りこぼさない。

**`run_sql` は文字列リテラルを自動修復する。** 似た別文字が混ざっていた場合は
正しいラベルに直し、直した内容を `corrections` として返す。黙って直さない。

**返り値に実行したSQLを含める。** 数字の出どころを確認できるようにするため。

`vocab.py` は `converter/codes` から機械生成したもの。手で編集しないこと。

## 動かす

```bash
pip install -r mcp_server/requirements.txt

python mcp_server/server.py                     # stdio
python mcp_server/server.py --http --port 8000  # HTTP（リモートコネクタ用）
```

Claude Code への登録:

```bash
claude mcp add npa-traffic-accident --scope user -- python <このファイルの絶対パス>/server.py
```

Claude Desktop（UIを見るならここ）への登録は `claude_desktop_config.json` に:

```json
{ "mcpServers": { "npa-traffic-accident": {
    "command": "python", "args": ["<絶対パス>/mcp_server/server.py"] } } }
```

**DuckDB がどこで走るか**は接続方式で決まる。

| 方式 | DuckDBの実行場所 | ホスティング |
|---|---|---|
| Claude Desktop + stdio | このPC | **不要** |
| claude.ai + トンネル（`--allow-host`） | このPC（起動している間だけ） | 不要だがPCが常時稼働である必要 |
| claude.ai + 常設サーバー | サーバー | 必要。設置先は未定（docs/DESIGN.md 11章） |

いずれの場合も R2 からは Range リクエストで数MBしか取らない。設置先は未定。

## 定義

指標・ディメンションの定義は [../CLAUDE.md](../CLAUDE.md) が正典。
ツールの説明文とサーバーの instructions はそこから移植している。
