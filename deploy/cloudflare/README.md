# Cloudflare Workers + Containers で常時公開する

[issue #3](https://github.com/shiwaku/npa-traffic-accident-analytics/issues/3) の案A。
`server.py --http` をそのままコンテナで動かし、Worker は転送だけする。PC に依存しない。

```
claude.ai        → Worker /s/<SECRET>/mcp ─┐
Web アプリ(web/) → Worker /web/mcp ────────┴→ Container(server.py --http) → R2 の parquet
```

Web アプリの入口は [docs/DESIGN_WEB.md](../../docs/DESIGN_WEB.md)。

| ファイル | 役割 |
|---|---|
| `Dockerfile` | `python:3.12-slim` + `mcp_server/`。ビルドコンテキストはリポジトリ直下（`.dockerignore` は許可リスト） |
| `entrypoint.py` | 起動時に parquet を R2 から `/data` に落としてから `server.py` を exec する（下記「なぜ」） |
| `wrangler.jsonc` | `instance_type: basic`（1/4 vCPU・1 GiB・4 GB disk）、`max_instances: 1` |
| `src/worker.ts` | `/mcp`（`SECRET_PATH` があれば `/s/<SECRET_PATH>/mcp`）、発表会用の `/e/<EVENT_PATH>/mcp`、`/web/mcp` をコンテナに通す。それ以外は 404 |
| `src/route.ts` | パスごとの振り分け。`WEB_ENABLED` が `"true"` でなければ `/web/mcp` と Web アプリの画面も 404。`EVENT_UNTIL` を過ぎたら `/e/…` も 404。`npm test` で確かめる |
| `src/gate.ts` | `/web/mcp` で通すメソッド・ツールの許可リスト（`run_sql` は通さない）。`npm test` で確かめる |
| `wrangler.jsonc` の `assets` / `vars` | Web アプリ（`web/dist`）を配る。`WEB_ENABLED` は回数制限（DESIGN_WEB.md 7.1）が入るまで `"false"` |
| `probe.py` | エンドポイントを叩いて応答時間を出す。デプロイ後の確認にも使う |

## 実測（2026-09-21）

ローカル Docker は `--memory=1g --cpus=0.25`（basic 相当）。実機は `wrangler deploy` 後に `probe.py` で計測。

| | ローカル: httpfs で R2 を直接読む | ローカル: 起動時に parquet を落とす（`entrypoint.py`） | **Cloudflare 実機**（同左） |
|---|---|---|---|
| コールドスタート（initialize が通るまで） | 18 s | 11.8 s（うちダウンロード 7.6 s / 96.6 MB） | 初回 79 s（provisioning 込み） |
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
- コールドスタートは十数秒。10 分に 1 回以上使うなら起きたまま。実機では 111.6 MB で 7.5 s
  （下の「再計測」）
- 実測はすべて Docker Desktop（Windows）上。Cloudflare の実機はデプロイして測る

## 再計測（2026-10-03、2025年版 111.6 MB）

`honhyo_2019-2025.parquet`（2,182,298件・111.6 MB）に切り替えた後、実機で `probe.py` を打った。
配置先は `wrangler containers instances` の `LOCATION` で `maa01`。

| | 2019〜2024年版（96.6 MB、09-21） | **2019〜2025年版（111.6 MB）** |
|---|---:|---:|
| コールドスタート（`inactive` から initialize が通るまで） | — | **7.5 s** |
| `seikatsu_dashboard`（全年・全国） | 0.38 s | 1.01〜1.55 s |
| `aggregate`（年別） | 0.23 s | 0.29〜0.49 s |
| `accident_map`（東京都・20,000点） | 0.88 s | 2.68〜3.88 s |

- コールドスタートはダウンロード込みで 7.5 s。手元 Docker の 11.8 s（96.6 MB）より速く、
  網内の R2 は手元の回線より速いという見込みは当たった。ダウンロード単体の秒数は取っていない
- 起動中の応答は 09-21 の 2.5〜4 倍。データ増は約15%なのでそれだけでは説明しにくい。
  `accident_map` は約 1 MB を返すので、配置先（`maa01`）と手元の距離が効いている可能性がある。
  09-21 の配置先は記録していないため判別できない。次から `LOCATION` も控える
- 10-03 は claude.ai のタブを閉じても 30 分以上 `running` のままだった（下の「課金とスリープ」と食い違う）。
  ほかのクライアントが繋がっていたのか、挙動が変わったのかは未確認。`wrangler deploy` し直すと
  ロールアウトでインスタンスが `inactive` になるので、コールドスタートはそれで測った

## 40人の同時利用（2026-10-10、issue #32）

`python probe.py load <URL> 40` で、40 セッションを 0.25 秒おきに張り、各セッションで
`seikatsu_dashboard` → `aggregate`（県別）→ `accident_map` ×2（県・半径1km）を**間を空けずに**呼んだ。
人が考える時間を入れていないので最悪の場合の数字。手元は Docker の `--cpus` / `--memory` で各サイズを模した。

| | エラー | dashboard p50 | aggregate p50 | map p50（p95） | メモリ最大 |
|---|---:|---:|---:|---:|---:|
| **basic・Cloudflare 実機** | 1 セッション※ | 38.6 s | 8.6 s | 81.7 s（89.7 s） | — |
| basic・手元（1/4 vCPU・1 GiB） | 0 | 40.1 s | 10.1 s | 79.7 s（85.1 s） | 753 MiB |
| standard-1・手元（1/2 vCPU・4 GiB） | 0 | 20.8 s | 8.1 s | 31.3 s（50.0 s） | 869 MiB |
| standard-2・手元（1 vCPU・6 GiB） | 0 | 12.3 s | 3.7 s | 16.7 s（25.7 s） | 836 MiB |

※ 手元の Python が TLS 証明書の検証に失敗したもの（`CERTIFICATE_VERIFY_FAILED`）。サーバー側の失敗ではない。

- **落ちない。** どのサイズでもエラー・OOM は 0。basic はメモリ 1 GiB の約75%まで使う
- **遅さは CPU で決まる。** vCPU を4倍にすると待ち時間はほぼ 1/4。実機の basic は手元の basic とほぼ同じ速さで、
  1人ずつの計測のような「実機のほうが速い」は同時アクセスでは成り立たない
- **当日は standard-2 に上げる。** 起きている間 約 $0.06/時（basic は約 $0.01/時）。上げたまま1か月起きていると約 $40 になるので、終わったら戻す。
  `max_instances` は 1 のまま（MCP セッションがコンテナのメモリ上にあるため、台数ではなくサイズで増やす）

### 当日の手順

```bash
cd deploy/cloudflare
# 前日: wrangler.jsonc の instance_type を "standard-2" にして
npx wrangler deploy
python probe.py load https://npa-traffic-accident-mcp.shi-works-worker.workers.dev/e/<EVENT_PATH>/mcp 40   # 実機で上の表と比べる

# 開始30分前: 起こしておく（寝ていると最初の1人が十数秒待つ）
python probe.py cold https://npa-traffic-accident-mcp.shi-works-worker.workers.dev/e/<EVENT_PATH>/mcp

# 終わったら: instance_type を "basic" に戻して
npx wrangler deploy
npx wrangler containers info <コンテナID>   # max_instances と vcpu・memory を確かめる
```

## 課金とスリープ（実測 2026-09-21）

Workers Paid は $5/月。そこに **basic インスタンスが起きている時間**の従量が乗る。
メモリとディスクは確保量に対して、CPU は実使用にだけ課金される。**寝ている間は課金されない。**

| | 無料枠/月 | 超過単価 | basic(1 GiB/4 GB) で 24 時間起動した場合 |
|---|---|---|---:|
| メモリ | 25 GiB-時 | $0.009/GiB-時 | $6.26 |
| ディスク | 200 GB-時 | $0.000252/GB-時 | $0.68 |
| vCPU | 375 vCPU-分 | $0.0012/vCPU-分 | ほぼ $0（1クエリ1〜2秒） |
| 送信量 | 1 TB | $0.025/GB | ほぼ $0（地図1回で約1 MB） |

### サイズ別の料金（2026-10-19 に公式の [Limits](https://developers.cloudflare.com/containers/platform-details/limits/) と [Pricing](https://developers.cloudflare.com/containers/pricing/) から計算）

起きている間は、メモリとディスクの分が確保量どおりにかかる（固定分）。CPU は使った分だけで、
CPU をずっと使い切ったときの上限を「CPU 上限込み」に書いた。40人同時のように混むと上限に近づく。

| サイズ | CPU | メモリ | ディスク | 固定分/時 | CPU 上限込み/時 | 30日起きっぱなし（固定分、無料枠を引いた額） |
|---|---|---|---|---:|---:|---:|
| `lite` | 1/16 vCPU | 256 MiB | 2 GB | $0.003 | $0.007 | $1.7 |
| **`basic`（ふだん）** | 1/4 vCPU | 1 GiB | 4 GB | $0.010 | $0.028 | $6.9 |
| `standard-1` | 1/2 vCPU | 4 GiB | 8 GB | $0.038 | $0.074 | $27 |
| **`standard-2`（発表会当日）** | 1 vCPU | 6 GiB | 12 GB | $0.057 | $0.129 | $41 |
| `standard-3` | 2 vCPU | 8 GiB | 16 GB | $0.076 | $0.220 | $54 |
| `standard-4` | 4 vCPU | 12 GiB | 20 GB | $0.113 | $0.401 | $81 |

- 寝ている間は 0。これとは別に Workers Paid の $5/月がかかる
- 発表会の数時間だけ `standard-2` にするなら、CPU を使い切っても1時間あたり約 $0.13
- ディスクが SSD かどうかは公式ページに書かれていない

**肝心なのは「いつ寝るか」。** `sleepAfter = "10m"` は正しく動くが、
**claude.ai のタブを開いている間はコンテナが寝ない。** MCP の streamable-http は
サーバー→クライアント方向の接続を張り続けるため、会話していなくても「使用中」と見なされる。

検証（`wrangler containers instances <ID>` の `STATE` を見る):

| 状態 | 10〜16分後 |
|---|---|
| コネクタ接続中・タブ開きっぱなし | `running`（1時間以上ずっと起きたまま） |
| コネクタを切断 | `inactive` |
| **接続したままタブを閉じる** | **`inactive`** |

つまり**切断は不要で、タブを閉じれば寝る**。コネクタは登録したままでよい。

| 使い方 | 月額の目安 |
|---|---:|
| 使い終わったらタブを閉じる | $5 + わずか |
| 日中ずっと claude.ai を開く（8h × 22日） | 約 $6.5 |
| 24時間開きっぱなし | 約 $12 |

切り忘れても 1 日あたり約 $0.23 なので、破滅的にはならない。
どうしても固定費を下げたいなら `instance_type` を `lite`（256 MiB・1/16 vCPU）にすると
24時間起動でも約 $6.7 になるが、実測ピーク 178 MiB に対して余裕が薄く、集計も数倍遅くなる。未検証。

**`wrangler containers list` の `LIVE INSTANCES` は稼働判定に使えない。**
寝ていても `1` のまま。`wrangler containers instances <ID>` の `STATE` を見ること。
ただし 2026-10-03 の再デプロイ後（version 6）は、応答している（initialize 0.4 s）のに
`STATE` が `stopped` と出た。`STATE` も当てにならない場合があるので、迷ったら `probe.py cold` の秒数で判断する
（起きていれば 1 s 未満、コールドなら数秒）。

## 分かっている落とし穴

- **`wrangler deploy` は Docker Desktop が起動していないと落ちる**（`The Docker CLI is needed to build
  the configured image before deploying`）。コードが同じでもイメージをビルドし直し、digest も変わる

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
(cd web && npm install && npm run build)  # Web アプリ。web/dist が無いと deploy が落ちる
cd deploy/cloudflare
npm install
npm test                                    # /web/mcp の許可リスト
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

## 発表会用の URL（issue #31）

来場者に配る URL は `SECRET_PATH` とは別の `EVENT_PATH` で発行する。配った URL は回収できないので、
止めても自分の claude.ai の登録（`/s/<SECRET_PATH>/mcp`）は生きるように分けてある。

いま配っている URL（2026-10-08 発行、10/22 23:59 JST に自動停止）:

```
https://npa-traffic-accident-mcp.shi-works-worker.workers.dev/e/HEh8-uaLCZxneNDUsleTKA/mcp
```

`EVENT_PATH` を作り直したら、ここと来場者向けの案内（[docs/EVENT_GUIDE.md](../../docs/EVENT_GUIDE.md)）を書き換える。

止め方は2つあり、どちらか一方で閉じる。

- **期限**: `wrangler.jsonc` の `vars.EVENT_UNTIL`（いまは `2026-10-22T23:59:59+09:00`）を過ぎると `/e/…` は 404。
  消し忘れの保険。未設定・日時として読めない値なら最初から閉じている
- **削除**: `npx wrangler secret delete EVENT_PATH` で即座に閉じる

```bash
cd deploy/cloudflare
npx wrangler deploy        # EVENT_UNTIL を変えたときだけ要る
python -c "import secrets; print(secrets.token_urlsafe(16))" | npx wrangler secret put EVENT_PATH
python probe.py run https://npa-traffic-accident-mcp.shi-works-worker.workers.dev/e/<EVENT_PATH>/mcp
# 配る URL: https://npa-traffic-accident-mcp.shi-works-worker.workers.dev/e/<EVENT_PATH>/mcp

# 終わったら
npx wrangler secret delete EVENT_PATH
```

`secret put` / `delete` は即座に反映され、再デプロイは要らない。期限を延ばすときは `EVENT_UNTIL` を直して `deploy`。
来場者の URL では `run_sql` も使える（`/s/…` と同じ入口なので）。重い SQL を投げられても
コンテナが1台詰まるだけで、課金は `sleepAfter` までの稼働時間しか増えない。

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
