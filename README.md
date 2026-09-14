# npa-traffic-accident-analytics

警察庁交通事故統計オープンデータの集計・可視化基盤。

変換済みデータ（GeoParquet）を Cloudflare R2 に配置し、ブラウザ上の DuckDB-WASM が
HTTP Range リクエストで必要な列だけを取得しながら集計する。サーバ側にデータベースや
API を持たず、静的ファイル配信のみで完結する。

- データ変換は前段リポジトリ [npa-traffic-accident-converter](../npa-traffic-accident-converter) が担当
- 個票の地図表示は同リポジトリの viewer（PMTiles）が担当
- 本リポジトリは**集計値の算出と閲覧**のみを扱う

## 状態

設計フェーズ。実装は未着手。

## ドキュメント

| | |
|---|---|
| [docs/DESIGN.md](docs/DESIGN.md) | 設計書。方式決定の根拠、データ仕様、UI構成、指標定義 |

## 方式の要点

96.6 MB の Parquet に対して、生活道路×若年層の6年分の集計を実行したときの実測値:

| | |
|---|---|
| 実転送量 | 4.07 MB（ファイル全体の 4.2%） |
| HTTPリクエスト数 | 62 |
| 所要時間 | 0.91秒 |

年を1年に絞ると 0.84 MB / 0.05秒。Parquet の列指向構造と row group 統計により、
クエリに必要な部分だけが転送される。Cloudflare R2 は egress 無料のため、
実質的な運用コストはゼロ。

詳細は [docs/DESIGN.md](docs/DESIGN.md) の 2章を参照。

## データ出典

[警察庁 交通事故統計情報のオープンデータ](https://www.npa.go.jp/publications/statistics/koutsuu/opendata/index_opendata.html)

政府標準利用規約（第2.0版）に準拠。
