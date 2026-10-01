# システム構成

いま動いている構成を図にしたもの。質問1つで何が起きるかは [HOW_IT_WORKS.md](HOW_IT_WORKS.md)、
方式決定の経緯は [DESIGN.md](DESIGN.md) にある。

---

## 1. 実行時の構成

利用者の Claude からデータまでの経路は2通りある。**どちらも同じ `mcp_server/server.py`** で、
違うのはサーバーの置き場所とデータの読み方だけ。

```mermaid
flowchart LR
    subgraph local["利用者のPC"]
        direction TB
        cc["Claude Code<br/>（ターミナル）"]
        cd["Claude Desktop"]
        srvL["server.py<br/>（stdio・常駐しない）"]
        duckL[("DuckDB<br/>+ httpfs")]
        cc -- "MCP / stdio" --> srvL
        cd -- "MCP / stdio" --> srvL
        srvL --> duckL
    end

    subgraph browser["ブラウザ"]
        ai["claude.ai"]
    end

    subgraph cf["Cloudflare"]
        direction TB
        worker["Worker<br/>src/worker.ts<br/>（/mcp だけ転送）"]
        subgraph ctr["Container（basic・max 1台・10分で sleep）"]
            direction TB
            entry["entrypoint.py<br/>起動時に parquet を落とす"]
            disk[("/data/honhyo.parquet<br/>ローカルディスク")]
            srvR["server.py --http<br/>:8080"]
            duckR[("DuckDB")]
            entry -- "ダウンロード 111.6MB" --> disk
            entry -- "exec" --> srvR
            srvR --> duckR
            duckR -- "ローカル読み" --> disk
        end
        r2[("R2 バケット shi-works<br/>shi-works.com/geoparquet/…/<br/>honhyo_2019-2025.parquet")]
        worker -- "Durable Object<br/>インスタンス名 main" --> srvR
    end

    ai -- "MCP / streamable-http<br/>HTTPS" --> worker
    duckL -- "HTTP Range<br/>必要な列だけ 約4MB" --> r2
    entry -- "HTTPS GET" --> r2
```

| | ローカル（stdio） | claude.ai（Cloudflare） |
|---|---|---|
| クライアント | Claude Code / Claude Desktop | claude.ai |
| サーバーの場所 | 利用者のPC。クライアントが子プロセスとして起動する | Cloudflare Containers。Worker が転送する |
| データの読み方 | httpfs で R2 を HTTP Range 読み（約4MB） | 起動時に parquet 全体を `/data` に落としてローカル読み |
| なぜその読み方か | 転送量が小さく、手元の回線なら数秒で返る | コンテナから httpfs で読むと往復回数が効いて 53 秒かかった。ローカルなら 0.4 秒 |
| 認証 | 不要（外に出ない） | `SECRET_PATH` 設定時は `/s/<秘密>/mcp` 以外を 404 |
| 手順 | [SETUP_WINDOWS](SETUP_WINDOWS.md) / [SETUP_MAC](SETUP_MAC.md) | [deploy/cloudflare/](../deploy/cloudflare/README.md) |

補足:

- Worker は `getContainer(env.MCP_CONTAINER, "main")` で**常に同じ1台**に送る。
  MCP のセッションはコンテナのメモリ上にあるため
- コンテナが寝るとディスクも消える。起きるたびに parquet を落とし直す（コールドスタート十数秒）
- 旧方式（手元の `server.py --http` を `cloudflared` の quick tunnel で公開）は図に含めていない。
  [REMOTE_CONNECTOR.md](REMOTE_CONNECTOR.md) 参照

---

## 2. ツールとビュー

MCP サーバーが公開するツールは5つ。うち3つは MCP Apps のビュー（`ui://` リソース）を持ち、
iframe を持つホスト（Claude Desktop・claude.ai）でだけ描画される。
Claude Code では同じツールが数字だけを返す。

```mermaid
flowchart LR
    subgraph server["server.py（MCPServer + Apps 拡張）"]
        direction TB
        t1["seikatsu_dashboard"]
        t2["accident_map"]
        t3["aggregate"]
        t4["list_values"]
        t5["run_sql"]
        defs["definitions.py<br/>生活道路などの定義"]
        vocab["vocab.py<br/>コード値 → ラベル"]
        t1 & t2 & t3 & t4 --> defs
        defs --> vocab
    end

    subgraph views["ビュー（app/dist/*.html・単一HTML）"]
        direction TB
        v1["mcp-app.html<br/>ui://…/seikatsu-dashboard.html"]
        v2["map-app.html<br/>ui://…/accident-map.html"]
        v3["table-app.html<br/>ui://…/aggregate-table.html"]
    end

    gsi[("国土地理院<br/>cyberjapandata.gsi.go.jp（ベクトルタイル）<br/>gsi-cyberjapan.github.io（glyphs / sprite）")]

    t1 -.-> v1
    t2 -.-> v2
    t3 -.-> v3
    v2 -- "ホストの iframe から直接取得<br/>（CSP で宣言したドメインのみ）" --> gsi
```

| ツール | ビュー | 外部通信 | 用途 |
|---|---|---|---|
| `seikatsu_dashboard` | 生活道路ダッシュボード | なし | 生活道路の経年推移（全事故を母数に併記） |
| `accident_map` | 事故地点マップ（MapLibre GL） | 地理院タイル | 絞り込んだ事故の点地図（既定 5,000・上限 20,000 点） |
| `aggregate` | 集計表 | なし | 条件で絞って集計。主にこれを使う |
| `list_values` | — | — | 列が取りうる値とコードの一覧 |
| `run_sql` | — | — | 生 SQL。似た別文字のリテラルは自動修復して `corrections` で返す |

生活道路の定義（strict / broad）は `definitions.py` だけが持つ。絞り込み・注記・
Claude に渡す説明文に加え、ビューの切り替えボタンもツールの返り値（`choices`）から作る。

ビューは `mcp_server/app/` を Vite + `vite-plugin-singlefile` で1枚の HTML に畳み込んだもの
（`npm run build`）。サンドボックス iframe は外部アセットを取りに行けないため、
JS/CSS はすべて HTML に埋め込まれている。

---

## 3. データを作る流れ

新年次を追加するときだけ動く。実行時の構成とは独立している。

```mermaid
flowchart LR
    npa[("警察庁<br/>交通事故統計<br/>オープンデータ CSV")]

    subgraph conv["npa-traffic-accident-converter（前段リポジトリ）"]
        direction TB
        c1["python -m converter --all --merge<br/>./export_geo.sh"]
        codes["converter/codes<br/>コード表"]
        c2[("output/<br/>honhyo_2019-2025_converted.parquet")]
        pm[("PMTiles<br/>個票の地図ビューア用")]
        c1 --> c2
        c1 --> pm
    end

    subgraph this["このリポジトリ"]
        direction TB
        b["pipeline/build_parquet.py<br/>資料年次の付与<br/>Snappy → zstd-9<br/>row group 131,072行 × 15"]
        out[("output/<br/>honhyo_2019-2025.parquet<br/>111.6MB")]
        vocab["mcp_server/vocab.py<br/>（機械生成）"]
        b --> out
    end

    subgraph r2["Cloudflare R2（バケット shi-works / shi-works.com）"]
        direction TB
        gp[("geoparquet/npa-traffic-accident-analytics/<br/>honhyo_2019-2025.parquet")]
        pmr[("pmtiles/npa-traffic-accident/")]
    end

    npa --> c1
    c2 --> b
    codes -. "生成" .-> vocab
    out -- "aws s3 cp<br/>--profile r2-shiworks<br/>immutable キャッシュ" --> gp
    pm --> pmr
```

- `資料年次` は前段の出力に無い。単年 CSV の行数を積み上げた区間で付与する（`--verify` で照合）
- ファイル名に年次範囲が入るので、年次を足すと**新しいキー**になる。
  immutable キャッシュのまま古い版と混ざらない
- 全 2,182,298 件の点表示は PMTiles + 既存ビューア（前段リポジトリ）の担当で、
  このリポジトリの `accident_map` とは別物
- 手順の詳細は [README](../README.md) の「データ更新」
