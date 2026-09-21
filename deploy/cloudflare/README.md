# Cloudflare Workers + Containers で常時公開する

[issue #3](https://github.com/shiwaku/npa-traffic-accident-analytics/issues/3) の案A。
`server.py --http` をそのままコンテナで動かし、Worker は転送だけする。PC に依存しない。

```
claude.ai → Worker(src/worker.ts、転送のみ) → Container(server.py --http) → R2 の parquet
```

| ファイル | 役割 |
|---|---|
| `Dockerfile` | `python:3.12-slim` + `mcp_server/`。ビルドコンテキストはリポジトリ直下（`.dockerignore` は許可リスト） |
| `entrypoint.py` | 起動時に parquet を R2 から `/data` に落としてから `server.py` を exec する（下記「なぜ」） |
| `wrangler.jsonc` | `instance_type: basic`（1/4 vCPU・1 GiB・4 GB disk）、`max_instances: 1` |
| `src/worker.ts` | `/mcp`（`SECRET_PATH` があれば `/s/<SECRET_PATH>/mcp`）だけをコンテナに通す |
| `probe.py` | エンドポイントを叩いて応答時間を出す。デプロイ後の確認にも使う |

## 実測（2026-09-21）

ローカル Docker は `--memory=1g --cpus=0.25`（basic 相当）。実機は `wrangler deploy` 後に `probe.py` で計測。

| | ローカル: httpfs で R2 を直接読む | ローカル: 起動時に parquet を落とす（`entrypoint.py`） | **Cloudflare 実機**（同左） |
|---|---|---|---|
| コールドスタート（initialize が通るまで） | 18 s | 11.8 s（うちダウンロード 7.6 s / 96.6 MB） | 初回 79 s（provisioning 込み）。2回目以降は未計測 |
| `seikatsu_dashboard`（全年・全国） | 53 s | 0.96 s | **0.38 s** |
| `aggregate`（年別） | 1.1 s | 0.28 s | **0.23 s** |
| `accident_map`（東京都・20,000点） | 30 s | 2.2 s | **0.88 s** |
| メモリ最大 | 103 MiB | 178 MiB | — |

**なぜローカルに落とすか。** httpfs は 1 クエリを数十〜数百の Range リクエストに分ける。
ホストの Python から直接叩いても dashboard 6 s・map 18 s で、コンテナで CPU を絞ると
53 s まで伸びた。CPU を 1 vCPU にしても 25 s で、CPU ではなく往復回数が効いている。
同じ parquet をローカルディスクから読むと 1/4 vCPU でも 1 秒。96 MB を起動時に 1 回落とす方が
圧倒的に安い。コンテナは `sleepAfter`（10 分）で寝るとディスクも消えるので、起きるたびに落とし直す。

判断:

- **`basic` で足りる。** メモリは 1 GiB の 2 割、CPU も 1 秒台。`lite`（256 MiB・1/16 vCPU）は試していない
- コールドスタートは十数秒。10 分に 1 回以上使うなら起きたまま。Cloudflare の網内なら
  R2 からの 96 MB は手元の回線より速いはずで、実機で測り直す
- 実測はすべて Docker Desktop（Windows）上。Cloudflare の実機はデプロイして測る

## 分かっている落とし穴

- **`wrangler dev` はコンテナを Windows で動かせない。** `Local development with containers is currently
  not supported on Windows. You should use WSL instead.` と言われて落ちる。Worker→コンテナの経路は
  実機デプロイで確かめる（WSL に Node 20+ を入れれば手元でも動くはず。未検証）
- **`shi-works.com` は `Python-urllib/*` の User-Agent を 403 にする**（Cloudflare の bot 対策）。
  `entrypoint.py` は名乗りを変えている。DuckDB の httpfs や curl は通る
- **地図ビュー（`ui://…/accident-map.html`、1.5 MB）は Python の `mcp` 2.2.0 クライアントだと
  `SSE stream ended without a response` で読めない。** サーバーは curl で見ると 1,573,058 バイトを
  正しく返しているので、クライアント側の問題。`probe.py` の当該行は無視してよい。
  claude.ai（個人アカウント）からは Worker 経由で描画まで確認済み（2026-09-21）
- **Team / Enterprise の claude.ai では、custom connector を追加できるのは組織の Owner だけ。**
  メンバーの Settings → Connectors には Add custom connector が出ない。組織で使うなら Owner に
  URL を組織の Connectors へ入れてもらう（全メンバーに配られる）。秘密パス方式は URL を知る人
  全員が使えるので、組織共有まで行くなら下の Access MCP portal に差し替える
- `--allow-host '*'` で Host ヘッダ検証を外している。コンテナには Worker 以外から到達できないので
  問題ないが、コンテナを直接公開する構成に変えるなら戻すこと

## デプロイ手順（済み。作り直すときも同じ）

```bash
cd deploy/cloudflare
npm install
npx wrangler login
npx wrangler deploy                         # Docker が動いている必要がある。初回は数分待つ
python -c "import secrets; print(secrets.token_urlsafe(24))" | npx wrangler secret put SECRET_PATH
python probe.py cold https://<worker>.workers.dev/s/<SECRET_PATH>/mcp
python probe.py run  https://<worker>.workers.dev/s/<SECRET_PATH>/mcp
```

`secret put` は Worker が存在してからでないと通らないので `deploy` が先。その間の数十秒は
`/mcp` が秘密パスなしで開くが、公開データの読み取り専用なので気にしない。
秘密パスの値は生成時に控えておく（Cloudflare 側からは読み出せない。失くしたら `secret put` し直す）。

現在のデプロイ: `https://npa-traffic-accident-mcp.shi-works-worker.workers.dev`（Worker 名
`npa-traffic-accident-mcp`、アカウント `993e6751…`）。秘密パス付きの URL は
claude.ai の Settings → Connectors → Add custom connector に登録済み（OAuth 欄は空）。

社内共有まで見込むなら、秘密パスの代わりに
[Cloudflare Access の MCP server portal](https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/)
に差し替える。portal が `ui://` リソースを素通しするかは繋がないと分からないので、
先に秘密パスで描画まで確認してから差し替える。

## 手元で動かす（Docker だけ）

```bash
# リポジトリ直下で
docker build -f deploy/cloudflare/Dockerfile -t npa-mcp:local .
docker run --rm -p 8080:8080 --memory=1g --cpus=0.25 npa-mcp:local
python deploy/cloudflare/probe.py run http://localhost:8080/mcp
```

`-e NPA_PARQUET_URL=/data/honhyo.parquet -v <dir>:/data:ro` を付けると手元の parquet を使う
（ダウンロードを飛ばす）。Git Bash では `MSYS_NO_PATHCONV=1` を付けないと `/data` が
`C:/Program Files/Git/data` に化ける。
