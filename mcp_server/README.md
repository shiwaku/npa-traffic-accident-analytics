# MCPサーバー

R2 上の GeoParquet を DuckDB で集計する MCP サーバー。
利用者は自分の Claude から日本語で聞くだけでよく、SQL も定義の知識も要らない。

## ツール

| | |
|---|---|
| `seikatsu_dashboard` | 生活道路の概況。**UI付き**（MCP Apps）。全事故を母数として同時に数える |
| `accident_map` | 絞り込んだ事故の発生地点を地図に描く。**UI付き**（MCP Apps + MapLibre） |
| `aggregate` | 条件を指定して集計する。細かい切り口はこれ |
| `list_values` | 項目の有効なコード値とラベルと件数を返す |
| `run_sql` | `aggregate` で表現できない集計のための逃げ道。読み取り専用 |

## UI（MCP Apps）

`seikatsu_dashboard`（ダッシュボード）と `accident_map`（地図）は
[MCP Apps 拡張](https://apps.extensions.modelcontextprotocol.io/)
（`io.modelcontextprotocol/ui`）で `ui://` リソースに紐づいており、対応ホストでは
サンドボックスiframeの中に描画される。

| | |
|---|---|
| 描画される | Claude Desktop、claude.ai |
| 描画されない | ターミナルの Claude Code（iframeを持たない）。ツールは同じ数字を返すので集計としては壊れない |

**サーバー側**は `mcp.server.apps`（`mcp>=2.2.0` に同梱、追加依存なし）。
**ビュー側**は `app/` を公式SDK `@modelcontextprotocol/ext-apps` で組み、
Vite で単一HTMLにバンドルしたものを `dashboard.py` が読む。

```bash
cd mcp_server/app && npm install && npm run build
# -> app/dist/mcp-app.html（ダッシュボード）と app/dist/map-app.html（地図）
```

ビューは2つあるが、単一HTML化はエントリが1つであることが前提のため
`vite build` を2回（`--mode map` 付き）走らせている。`npm run build` が両方やる。

ハンドシェイク（`ui/initialize`）・`tool-result` の受信・`tools/call` の送出・
サイズ通知は SDK の `App` クラスに任せる。**ここを手書きしないこと。**
`ui/initialize` の params は `appInfo` / `appCapabilities` / `protocolVersion` で、
`appInfo` を `clientInfo` と書くとホストによっては黙って描画されない。

`vite-plugin-singlefile` は必須。サンドボックスiframeは外部アセットを取りに
行けないため、JS/CSSがHTMLに畳み込まれていないとビューは動かない。
ダッシュボードは外部リソースを一切読まない（グラフはインラインSVG）ので
`_meta.ui.csp` を宣言していない。

**地図ビューだけは外部と通信する。** `add_html_resource(csp=ResourceCsp(...))` で
地理院のタイル（`cyberjapandata.gsi.go.jp`）とグリフ・スプライト
（`gsi-cyberjapan.github.io`）を宣言している。宣言しないドメインへの通信は
ホストのCSPが止める。**Artifact と違い、MCP Apps は宣言すれば外部を読める。**

| | |
|---|---|
| 背景地図 | 地理院 最適化ベクトルタイル（淡色）。スタイルは `src/gsi-pale.json` に取り込み済み |
| 由来 | [shiwaku/dm-converter](https://github.com/shiwaku/dm-converter) の `viewer/public/pale.json`。ダーク化の明度反転も同リポジトリの手法 |
| タイルの参照先 | 素のスタイルは `pmtiles://` を指すが、pmtilesライブラリを足さずに済むよう XYZ (`.pbf`) に向け直している |
| 描画 | MapLibre GL JS。Web Worker（blob）は参照ホストのCSP `worker-src 'self' blob:` で動く |

MapLibre に渡す色は `getComputedStyle(...).getPropertyValue()` の値をそのまま使えない。
`light-dark(#a, #b)` の宣言が返り、MapLibre は "Could not parse color" でそのレイヤーを
描かない（**地図自体は出るので気付きにくい**）。ダミー要素に載せて算出値を読むこと。

ビュー内の **strict / broad トグル**は `visibility: ["model","app"]` の同じツールを
`app.callServerTool(...)` で呼び直す。会話に戻らずに定義を切り替えられるので、
**件数が1.79倍動くこと**をその場で確かめられる。地図ビューも同じ仕組みで、
生活道路の定義と「死亡事故のみ」はサーバーを呼び直し（該当件数が変わるため）、
年の絞り込みは受け取った点だけを絞る（再問い合わせなし）。

点が `max_points`（既定 5,000・上限 `_MAX_POINTS_CAP` = 20,000）を超えるときは
**内容のハッシュ順で上位を採る**。
`USING SAMPLE ... REPEATABLE` は並列スキャンだと再現せず、同じ条件で呼び直すたびに
点が入れ替わる（実測）。切り替えたつもりのない差が「変化」に見えてしまう。

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
2019〜2024の全年次を統合しているので、年次をまたいでも取りこぼさない
（2025年はコード値の追加がなく、2024年のコード表をそのまま使う）。

**定義は `definitions.py` の1か所に置く。** 生活道路の定義がコード・注記・説明文・
ビューに散らばっていると、1か所だけ直して食い違う。下の「定義」参照。

**`run_sql` は文字列リテラルを自動修復する。** 似た別文字が混ざっていた場合は
正しいラベルに直し、直した内容を `corrections` として返す。黙って直さない。

**DuckDB は parquet 1つしか読めないように閉じている。** `run_sql` は利用者の SQL を
そのまま実行するが、DuckDB は SELECT 文の中でもファイルや URL を読む関数を使える。
`_open_db()` で外部アクセスを止め（`enable_external_access=false`）、読めるパスを
parquet だけに絞り（`allowed_paths`）、`lock_configuration` で SQL から戻せなくしている。
**DuckDB 1.2.2 以上が要る**（1.1.3 には `allowed_paths` が無く、起動時に止まる）。
`run_sql` はさらに、DuckDB のパーサで「SELECT 文が1つだけ」であることを確かめ、
20秒（`RUN_SQL_TIMEOUT_S`）で終わらなければ中断する。

**接続は呼び出しごとに分ける。** MCP SDK は同期関数のツールをスレッドで並列に実行する。
1本の接続を共有すると、DuckDB 1.1.3 ではプロセスが落ち、1.5.5 では**黙って間違った数字を返す**
（40並列・160回で正しかったのは18回）。`con()` は毎回 `cursor()` を返す。

**利用者に伝えたいエラーは `ToolError` で出す。** それ以外の例外は SDK が中身を隠し、
Claude には「Error executing tool ...」しか届かない。緯度経度の取り違えのような案内が
伝わらなくなる。

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
**サーバーが使う定義は `definitions.py` の1か所だけに置く。**

| `definitions.py` にあるもの | そこから作られるもの |
|---|---|
| `SEIKATSU`（生活道路 strict / broad のコードと説明） | 絞り込みの WHERE 句、結果の注記、instructions、ツールの説明文、`list_values` の注記、ビューの切り替えボタン |
| `YOUNG_AGE` / `WALK_BIKE`（0〜24歳の歩行者・自転車） | ダッシュボードの「0〜24歳の歩行者・自転車」列 |

コードは `vocab.py` のキーで書き、ラベル文字列は書かない。import 時に
「引数の型と `SEIKATSU` のキーが一致しているか」「コードが `vocab.py` にあるか」を確かめ、
ずれていればサーバーが起動しない。黙って0件になるより早く気づける。

```bash
python mcp_server/definitions.py   # 定義ごとのコードとラベルを一覧する
```

定義を足す手順は [../CLAUDE.md](../CLAUDE.md) の「定義を足すとき」。
