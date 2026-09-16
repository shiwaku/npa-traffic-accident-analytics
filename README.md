# npa-traffic-accident-analytics

警察庁交通事故統計オープンデータ（2019〜2024年、1,895,275件）を Cloudflare R2 上の
GeoParquet として公開し、Claude Code との対話で集計・可視化する。

サーバもデータベースもWebアプリも持たない。**R2 上のファイル1つと `CLAUDE.md` だけ**で成立する。

```
「生活道路の若年層の事故件数の経年推移」
   ↓
Claude Code ── CLAUDE.md の定義を読んで SQL を組み立てる
   ↓
DuckDB + httpfs ── HTTP Range で必要な列だけ取得（約4MB）
   ↓
Cloudflare R2 / shi-works.com
   ↓
表（ターミナル）/ グラフ・地図（Artifact）
```

## データ

```
https://shi-works.com/geoparquet/npa-traffic-accident-analytics/honhyo_2019-2024.parquet
```

| | |
|---|---|
| 行数 | 1,895,275（本票、1行＝1事故） |
| サイズ | 96.6 MB（zstd-9、row group 131,072行 × 15） |
| 形式 | GeoParquet 1.0.0（EPSG:4326） |

96.6 MB のうち、集計で実際に転送されるのは約4MB。Parquet の列指向構造により
`SELECT` した列の Range リクエストだけが飛ぶ。年を絞ると 0.84MB まで下がる。

```python
import duckdb
URL = 'https://shi-works.com/geoparquet/npa-traffic-accident-analytics/honhyo_2019-2024.parquet'
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute(f"CREATE VIEW honhyo AS SELECT * FROM read_parquet('{URL}')")
```

実測: ビュー作成 1.33秒 / 全6年の集計 2.05秒。

## ドキュメント

| | |
|---|---|
| [CLAUDE.md](CLAUDE.md) | **指標・ディメンション定義の正典。集計前に必読** |
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | **いま動いているものの仕組み。質問1つで何が起きるか** |
| [docs/DESIGN.md](docs/DESIGN.md) | 設計書。方式決定の経緯と、採らなかった方式 |
| [docs/SETUP_MAC.md](docs/SETUP_MAC.md) | **別のマシン（Mac）の Claude Desktop に入れる手順** |
| [docs/SETUP_WINDOWS.md](docs/SETUP_WINDOWS.md) | **Windows の Claude Desktop から使う手順（経路A）** |
| [docs/REMOTE_CONNECTOR.md](docs/REMOTE_CONNECTOR.md) | claude.ai から使う（トンネル経由のリモートコネクタ） |
| [docs/REMOTE_CONNECTOR_MANUAL.md](docs/REMOTE_CONNECTOR_MANUAL.md) | 上を手で動かす手順（Windows）。コマンドと詰まりどころ |
| [docs/VERIFY_PROMPTS.md](docs/VERIFY_PROMPTS.md) | 動作確認用プロンプトと期待値 |
| [mcp_server/README.md](mcp_server/README.md) | MCPサーバーのツールと設計の要点 |

`CLAUDE.md` には、このデータを正しく集計するために不可欠な知識が入っている。

- 生活道路の定義（どのコードを含めるかで結果が約2倍動く）
- 年齢は7区分の年齢層コードであり「10代の事故」は原理的に集計できないこと
- 当事者A/Bが過失の重さによる区分で、被害者区分ではないこと
- 年齢と当事者種別を同一当事者でペア判定する必要があること
- 資料年次と発生年の違い（最新年が約3%過少になる）
- **コード表のラベルが全角ハイフンマイナス U+FF0D と全角チルダ U+FF5E を使っており、
  似た別文字を混ぜるとエラーにならず0件が返ること**

## データ更新

```bash
# 前段リポジトリで変換（新年次追加時）
cd ../npa-traffic-accident-converter
python -m converter --all --merge && ./export_geo.sh

# 資料年次の付与 + 配信向け最適化
cd ../npa-traffic-accident-analytics
python pipeline/build_parquet.py --verify

# R2 へ
aws s3 cp output/honhyo_2019-2024.parquet \
  s3://shi-works/geoparquet/npa-traffic-accident-analytics/honhyo_2019-2024.parquet \
  --profile r2-shiworks \
  --content-type application/vnd.apache.parquet \
  --cache-control "public, max-age=31536000, immutable"
```

## 関連リポジトリ

| | |
|---|---|
| [npa-traffic-accident-converter](../npa-traffic-accident-converter) | 警察庁CSV → 変換 → GeoParquet。個票の地図ビューア（PMTiles）も同梱 |

## データ出典

[警察庁 交通事故統計情報のオープンデータ](https://www.npa.go.jp/publications/statistics/koutsuu/opendata/index_opendata.html)

政府標準利用規約（第2.0版）に準拠。
