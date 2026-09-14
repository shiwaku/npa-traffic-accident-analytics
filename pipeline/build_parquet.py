# -*- coding: utf-8 -*-
"""マージ済み GeoParquet に資料年次を付与し、R2 配信用に書き直す。

    python pipeline/build_parquet.py
    python pipeline/build_parquet.py --src ../npa-traffic-accident-converter/output/honhyo_2019-2024_converted.parquet

前段リポジトリの出力には「どの年のファイル由来か」の情報が無い。単年CSVでは
ファイル名が年次を表しているが、マージすると失われる。この列が無いと公表値と
一致する集計ができない(詳細は CLAUDE.md の「年次基準」)。

行の対応付けは位置ベースで行う。マージは年次順の concat であり、座標欠損による
行落ちも無い(全行に座標がある)ため、単年CSVの行数を積み上げた区間が
そのまま各年のブロックになる。--verify でこの前提を全年について照合する。

あわせて配信向けに最適化する。

    圧縮      : Snappy → zstd-9        128.1 MB → 96.6 MB
    row group : 2個(各104万行) → 15個(各131,072行)

row group が大きいままだと年やコードで絞っても読み飛ばせない。資料年次で
整列済みなので、細かく切れば統計によるプルーニングが効く(全6年 4.07MB に対し
1年に絞ると 0.84MB)。GeoParquet メタデータは保持するので geopandas / QGIS から
引き続き読める。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT.parent / 'npa-traffic-accident-converter' / 'output' / 'honhyo_2019-2024_converted.parquet'
DEFAULT_DST = ROOT / 'output' / 'honhyo_2019-2024.parquet'

ROW_GROUP = 128 * 1024
YEAR_FIELD = pa.field('資料年次', pa.int16())


def source_csv(year: int) -> Path:
    return DEFAULT_SRC.parent / f'honhyo_{year}_converted.csv'


def year_row_counts(years: range) -> dict[int, int]:
    """単年CSVの行数。資料年次ブロックの境界になる。"""
    import pandas as pd
    counts = {}
    for y in years:
        path = source_csv(y)
        if not path.exists():
            raise SystemExit(f'単年CSVが無い: {path}\n'
                             f'先に converter 側で python -m converter --all を実行すること')
        counts[y] = len(pd.read_csv(path, dtype=str, low_memory=False, usecols=['発生日時_年']))
        print(f'  {y}: {counts[y]:,} 行', file=sys.stderr)
    return counts


def verify_order(src: Path, counts: dict[int, int]) -> None:
    """位置ベースの割り当てが妥当か、行の中身まで照合する。"""
    import pandas as pd
    cols = ['発生日時_年', '本票番号', '都道府県名']
    p = pq.read_table(src, columns=cols).to_pandas()
    off = 0
    for y, n in counts.items():
        d = pd.read_csv(source_csv(y), dtype=str, low_memory=False, usecols=cols)
        blk = p.iloc[off:off + n].reset_index(drop=True)
        if not (blk['本票番号'].equals(d['本票番号']) and blk['都道府県名'].equals(d['都道府県名'])):
            raise SystemExit(f'{y}年のブロックが単年CSVと一致しない。'
                             f'マージの並び順が変わった可能性がある')
        print(f'  {y}: 行の完全一致 OK', file=sys.stderr)
        off += n


def build(src: Path, dst: Path, counts: dict[int, int]) -> None:
    f = pq.ParquetFile(src)
    total = sum(counts.values())
    if f.metadata.num_rows != total:
        raise SystemExit(f'行数が合わない: parquet {f.metadata.num_rows:,} / 単年CSV合計 {total:,}\n'
                         f'座標欠損による行落ちが発生している可能性がある')

    src_schema = f.schema_arrow
    new_schema = pa.schema([YEAR_FIELD] + list(src_schema), metadata=src_schema.metadata)

    bounds, acc = [], 0
    for y, n in counts.items():
        bounds.append((acc, acc + n, y))
        acc += n

    def years_for(start: int, length: int) -> list[int]:
        out = []
        for lo, hi, y in bounds:
            s, e = max(lo, start), min(hi, start + length)
            if s < e:
                out.extend([y] * (e - s))
        return out

    dst.parent.mkdir(parents=True, exist_ok=True)
    writer = pq.ParquetWriter(dst, new_schema, compression='zstd',
                              compression_level=9, write_statistics=True)
    pos, buf, buf_rows = 0, [], 0

    def flush():
        nonlocal buf, buf_rows
        if buf:
            writer.write_table(pa.concat_tables(buf), row_group_size=ROW_GROUP)
            buf, buf_rows = [], 0

    for batch in f.iter_batches(batch_size=65536):
        yrs = pa.array(years_for(pos, batch.num_rows), type=pa.int16())
        tbl = pa.Table.from_batches([batch]).add_column(0, YEAR_FIELD, yrs)
        buf.append(tbl.replace_schema_metadata(new_schema.metadata))
        buf_rows += batch.num_rows
        pos += batch.num_rows
        if buf_rows >= ROW_GROUP:
            flush()
    flush()
    writer.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', type=Path, default=DEFAULT_SRC)
    ap.add_argument('--dst', type=Path, default=DEFAULT_DST)
    ap.add_argument('--from-year', type=int, default=2019)
    ap.add_argument('--to-year', type=int, default=2024)
    ap.add_argument('--verify', action='store_true',
                    help='位置ベースの割り当てを行の中身まで照合する(遅い)')
    args = ap.parse_args()

    if not args.src.exists():
        raise SystemExit(f'入力が無い: {args.src}')

    years = range(args.from_year, args.to_year + 1)
    print('単年CSVの行数を数える', file=sys.stderr)
    counts = year_row_counts(years)

    if args.verify:
        print('行の対応を照合する', file=sys.stderr)
        verify_order(args.src, counts)

    t = time.time()
    print(f'{args.src.name} → {args.dst.name}', file=sys.stderr)
    build(args.src, args.dst, counts)

    m = pq.ParquetFile(args.dst).metadata
    print(f'完了 {time.time() - t:.1f}秒', file=sys.stderr)
    print(f'  {m.num_rows:,} 行 / row group {m.num_row_groups} 個')
    print(f'  {args.src.stat().st_size / 1e6:.1f} MB → {args.dst.stat().st_size / 1e6:.1f} MB')
    print(f'\nR2 へは以下でアップロードする:')
    print(f'  aws s3 cp {args.dst} \\\n'
          f'    s3://shi-works/geoparquet/npa-traffic-accident-analytics/{args.dst.name} \\\n'
          f'    --profile r2-shiworks \\\n'
          f'    --content-type application/vnd.apache.parquet \\\n'
          f'    --cache-control "public, max-age=31536000, immutable"')


if __name__ == '__main__':
    main()
