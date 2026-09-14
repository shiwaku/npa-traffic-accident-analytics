# -*- coding: utf-8 -*-
"""警察庁交通事故統計を集計するMCPサーバー。

R2 上の GeoParquet を DuckDB が HTTP Range で部分取得しながら集計する。
96.6MB のファイルに対し、1クエリで転送されるのは数MB。

    python mcp_server/server.py                    # stdio（Claude Code から使う）
    python mcp_server/server.py --http --port 8000 # HTTP（リモートコネクタとして公開）

このデータは定義を知らずに集計すると、エラーにならずに誤った数字が出る。
そのため引数はラベル文字列ではなく**コード値**で受け取り、サーバー側で
正しいラベルへ変換する。コード表のラベルは全角ハイフンマイナス(U+FF0D)と
全角チルダ(U+FF5E)を含み、似た別文字を1つ混ぜると0件が返るため。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from typing import Any, Literal

import duckdb
from mcp.server.mcpserver import MCPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vocab  # noqa: E402

PARQUET_URL = os.environ.get(
    "NPA_PARQUET_URL",
    "https://shi-works.com/geoparquet/npa-traffic-accident-analytics/honhyo_2019-2024.parquet",
)

# 生活道路のプリセット。この選択で件数が約2倍変わる
SEIKATSU = {
    "strict": ["01", "02", "11"],          # 自道路（交差点は両方）が5.5m未満
    "broad": ["01", "02", "11", "14", "17"],  # 片側のみ5.5m未満の交差点も含む
}

# 北海道は元データが方面本部別(札幌・旭川・釧路・函館・北見)。
# 都道府県として集計するときは合算しないと、北海道だけ5つに割れて順位が狂う。
PREF_EXPR = ("CASE WHEN \"都道府県名\" LIKE '北海道%' THEN '北海道' "
             "ELSE \"都道府県名\" END")

GROUP_COLUMNS = {
    "year": None,  # year_basis で決まる
    "month": '"発生日時_月"',
    "prefecture": PREF_EXPR,
    "police_station": '"警察署等名"',
    "road_width": '"車道幅員"',
    "road_type": '"路線名"',
    "road_shape": '"道路形状"',
    "zone": '"ゾーン規制"',
    "accident_type": '"事故類型"',
    "accident_content": '"事故内容"',
    "day_night": '"昼夜"',
    "weather": '"天候"',
    "age_a": '"年齢（当事者A）"',
    "age_b": '"年齢（当事者B）"',
    "party_type_a": '"当事者種別（当事者A）"',
    "party_type_b": '"当事者種別（当事者B）"',
}

_con: duckdb.DuckDBPyConnection | None = None
_pref_map: dict[str, list[str]] = {}
_known_labels: set[str] = set()


def con() -> duckdb.DuckDBPyConnection:
    global _con
    if _con is None:
        c = duckdb.connect()
        c.execute("INSTALL httpfs; LOAD httpfs;")
        c.execute(f"CREATE VIEW honhyo AS SELECT * FROM read_parquet('{PARQUET_URL}')")
        _con = c
        _build_lookups()
    return _con


def _build_lookups() -> None:
    """都道府県の名寄せ表と、既知ラベルの集合を作る。

    元データの都道府県名は51種。北海道が方面本部別に分かれ、「東京」「大阪」に
    都・府が付かない。利用者が「東京都」「北海道」と書いても通るようにする。
    """
    rows = [r[0] for r in _con.execute(
        'SELECT DISTINCT "都道府県名" FROM honhyo WHERE "都道府県名" IS NOT NULL').fetchall()]
    for raw in rows:
        keys = {raw}
        if raw.startswith("北海道"):
            keys.add("北海道")
        else:
            keys |= {raw, raw + "都", raw + "府", raw + "県"}
        for k in keys:
            _pref_map.setdefault(k, [])
            if raw not in _pref_map[k]:
                _pref_map[k].append(raw)
    _known_labels.update(rows)
    for d in (vocab.ROAD_WIDTH, vocab.AGE, vocab.PARTY_TYPE,
              vocab.ACCIDENT_TYPE, vocab.ZONE, vocab.DAY_NIGHT):
        for labels in d.values():
            _known_labels.update(labels)


def _norm(s: str) -> str:
    """紛らわしい文字を潰した比較用の形。"""
    s = s.replace("－", "-").replace("−", "-").replace("ー", "-")
    s = s.replace("～", "~").replace("〜", "~")
    return unicodedata.normalize("NFKC", s)


_NORM_INDEX: dict[str, str] = {}


def _repair(lit: str) -> tuple[str, bool]:
    """似た別文字で書かれたラベルを正しい表記へ直す。直したかどうかも返す。"""
    if lit in _known_labels:
        return lit, False
    if not _NORM_INDEX:
        for lab in _known_labels:
            _NORM_INDEX.setdefault(_norm(lab), lab)
    fixed = _NORM_INDEX.get(_norm(lit))
    return (fixed, True) if fixed else (lit, False)


def _codes_to_labels(codes: list[str], table: dict[str, list[str]], what: str) -> list[str]:
    out: list[str] = []
    unknown: list[str] = []
    for code in codes:
        c = str(code).zfill(2) if len(str(code)) == 1 else str(code)
        labels = table.get(c)
        if labels is None:
            unknown.append(code)
            continue
        out.extend(labels)
    if unknown:
        raise ValueError(
            f"{what} に未知のコード {unknown} が指定された。"
            f"list_values('{what}') で有効なコードを確認すること")
    return out


def _quote(values: list[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


server = MCPServer(
    name="npa-traffic-accident",
    title="警察庁交通事故統計",
    instructions="""警察庁の交通事故統計(本票、2019〜2024年、1,895,275件)を集計する。

集計の前に必ず知っておくこと:

1. 年齢は実年齢ではなく**年齢層コード**で、最小区分が 0〜24歳。
   「10代の事故」「未成年の事故」「20代の事故」は原理的に集計できない。
   聞かれたら、それらしい数字を出さずにこの制約を伝えること。

2. 「生活道路」は車道幅員5.5m未満の道路。交差点の扱いで2通りあり、
   strict(交差する両方が5.5m未満)と broad(片側のみも含む)で**件数が約2倍変わる**。
   どちらを使ったか必ず利用者に明示すること。曖昧なら先に確認する。

3. 当事者Aは**過失が最も重い側**、Bはその相手方。被害者区分ではない。
   実態としてはBが死傷している事故が77.5%だが、Bが無傷の事故も16.8%ある。

4. 年齢と当事者種別は**同一当事者でペア判定**される。
   party_scope='either' は「A または B が条件を満たす事故」を行単位で数えるので、
   二重計上は起きない。ただし歩行者だけの集計と自転車だけの集計を足すと、
   両方に該当する事故(6年間で384件)を二重に数えることになる。

5. 年次は既定が資料年次(計上年)。各年の全事故件数が警察庁公表値と一致する。
   発生年で数えると最新年が約3%過少に出るため、経年推移には向かない。

6. 本票は**人身事故のみ**。物損事故は含まれない。
   死亡事故は全期間で16,266件しかなく、細かく絞ると年数件になりトレンドを読めない。

実数の増減だけで語らないこと。2020年はコロナ禍で全体件数が前年比19%減しており、
母数の変化を無視すると傾向を読み誤る。構成比や指数を併せて見ること。""",
)


@server.tool(
    title="集計する",
    description="""交通事故を条件で絞り込んで集計する。主にこれを使う。

引数はラベル文字列ではなくコード値で指定する(例: 車道幅員なら '01','02','11')。
有効なコードは list_values で確認できる。

生活道路を見るときは seikatsu='strict' または 'broad' を使う。
road_width を直接指定するより意図が明確になる。

年齢と当事者種別を同時に指定すると、同一当事者でのペア判定になる。
party_scope='either' なら「AまたはBがその年齢かつその種別」の事故を行単位で数える。

順序は既定で、年や月を含むときはキー順、それ以外は件数の多い順。
limit で上位を絞るときは件数順が使われるので順位を誤らない。

返り値には実行したSQLが含まれる。数字に疑問があれば確認すること。""",
)
def aggregate(
    group_by: list[str] | None = None,
    year_basis: Literal["資料年次", "発生年"] = "資料年次",
    year_from: int | None = None,
    year_to: int | None = None,
    seikatsu: Literal["strict", "broad"] | None = None,
    road_width: list[str] | None = None,
    prefecture: list[str] | None = None,
    party_age: list[str] | None = None,
    party_type: list[str] | None = None,
    party_scope: Literal["A", "B", "either"] = "either",
    accident_type: list[str] | None = None,
    day_night: list[str] | None = None,
    fatal_only: bool = False,
    zone30_only: bool = False,
    order_by: Literal["keys", "count"] | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    c = con()
    group_by = group_by or ["year"]
    year_col = '"資料年次"' if year_basis == "資料年次" else '"発生日時_年"'
    notes: list[str] = []

    selects, groups = [], []
    for g in group_by:
        if g == "year":
            selects.append(f"{year_col} AS 年")
            groups.append(year_col)
        elif g in GROUP_COLUMNS:
            selects.append(f"{GROUP_COLUMNS[g]} AS {g}")
            groups.append(GROUP_COLUMNS[g])
        else:
            raise ValueError(f"group_by に未知の項目 '{g}'。使えるのは {sorted(GROUP_COLUMNS)}")

    where: list[str] = []

    if seikatsu:
        if road_width:
            raise ValueError("seikatsu と road_width は同時に指定できない")
        road_width = SEIKATSU[seikatsu]
        notes.append(
            "生活道路 = 車道幅員5.5m未満。"
            + ("strict(交差する両方が5.5m未満)で絞った。broad にすると件数は約2倍になる"
               if seikatsu == "strict"
               else "broad(片側のみ5.5m未満の交差点を含む)で絞った。幹線側の事故も含まれる"))
    if road_width:
        where.append(f'"車道幅員" IN ({_quote(_codes_to_labels(road_width, vocab.ROAD_WIDTH, "road_width"))})')

    if year_from is not None:
        where.append(f"{year_col} >= {int(year_from)}")
    if year_to is not None:
        where.append(f"{year_col} <= {int(year_to)}")
    if year_basis == "発生年":
        notes.append("発生年で集計した。最新年は翌年ファイルに計上される分が欠けるため約3%過少に出る")

    if prefecture:
        expanded: list[str] = []
        for p in prefecture:
            hit = _pref_map.get(p) or _pref_map.get(_repair(p)[0])
            if not hit:
                raise ValueError(f"未知の都道府県 '{p}'。list_values('prefecture') を参照")
            expanded.extend(hit)
        where.append(f'"都道府県名" IN ({_quote(expanded)})')
        if any(p.startswith("北海道") for p in expanded) and len(expanded) > 1:
            notes.append("北海道は元データが方面本部別(札幌・旭川・釧路・函館・北見)のため合算した")

    if party_age or party_type:
        conds = []
        for side in (["A"] if party_scope == "A" else ["B"] if party_scope == "B" else ["A", "B"]):
            sub = []
            if party_age:
                sub.append(f'"年齢（当事者{side}）" IN ({_quote(_codes_to_labels(party_age, vocab.AGE, "party_age"))})')
            if party_type:
                sub.append(f'"当事者種別（当事者{side}）" IN ({_quote(_codes_to_labels(party_type, vocab.PARTY_TYPE, "party_type"))})')
            conds.append("(" + " AND ".join(sub) + ")")
        where.append("(" + " OR ".join(conds) + ")")
        if party_age and "01" in [str(a).zfill(2) for a in party_age]:
            notes.append("年齢 0〜24歳 は年齢層コードの最小区分。10代のみの切り出しは不可能")
        if party_scope == "either":
            notes.append("当事者AまたはBが条件を満たす事故を行単位で1件と数えた(二重計上なし)")

    if accident_type:
        where.append(f'"事故類型" IN ({_quote(_codes_to_labels(accident_type, vocab.ACCIDENT_TYPE, "accident_type"))})')
    if day_night:
        where.append(f'"昼夜" IN ({_quote(_codes_to_labels(day_night, vocab.DAY_NIGHT, "day_night"))})')
    if fatal_only:
        where.append("\"事故内容\" = '死亡事故'")
        notes.append("死亡事故は全期間で16,266件と少ない。細かく絞ると年数件になり傾向を読めない")
    if zone30_only:
        where.append("\"ゾーン規制\" = 'ゾーン30'")

    where_sql = "WHERE " + "\n  AND ".join(where) + "\n" if where else ""
    keys = ", ".join(str(i + 1) for i in range(len(groups)))

    # 時系列はキー順(年月の並び)、それ以外は件数の多い順が既定。
    # limit で切るときキー順のままだと、上位ではなく先頭が返って順位を誤らせる。
    if order_by is None:
        order_by = "keys" if ({"year", "month"} & set(group_by)) else "count"
    order_sql = keys if order_by == "keys" else f"{len(groups) + 1} DESC"
    if order_by == "count" and limit < 60:
        notes.append(f"件数の多い順に上位{limit}件を返した")
    sql = (f"SELECT {', '.join(selects)}, count(*) AS 件数, "
           f'sum(CAST("死者数" AS INTEGER)) AS 死者数, '
           f'sum(CAST("負傷者数" AS INTEGER)) AS 負傷者数\n'
           f"FROM honhyo\n"
           f"{where_sql}"
           f"GROUP BY {keys}\n"
           f"ORDER BY {order_sql}\n"
           f"LIMIT {int(limit)}")

    cur = c.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {"rows": rows, "row_count": len(rows), "notes": notes, "sql": sql}


@server.tool(
    title="コード値を調べる",
    description="""指定した項目の、有効なコード値とラベルと実データ件数を返す。
aggregate に渡すコードが分からないときに使う。

field に使えるのは: road_width, age, party_type, accident_type, zone, day_night,
prefecture, road_type, road_shape, weather""",
)
def list_values(field: str) -> dict[str, Any]:
    c = con()
    tables = {"road_width": (vocab.ROAD_WIDTH, "車道幅員"),
              "age": (vocab.AGE, "年齢（当事者A）"),
              "party_type": (vocab.PARTY_TYPE, "当事者種別（当事者A）"),
              "accident_type": (vocab.ACCIDENT_TYPE, "事故類型"),
              "zone": (vocab.ZONE, "ゾーン規制"),
              "day_night": (vocab.DAY_NIGHT, "昼夜")}
    if field in tables:
        table, col = tables[field]
        counts = dict(c.execute(
            f'SELECT "{col}", count(*) FROM honhyo GROUP BY 1').fetchall())
        items = [{"code": code,
                  "labels": labels,
                  "count": sum(counts.get(l, 0) for l in labels)}
                 for code, labels in sorted(table.items())]
        note = None
        if field == "road_width":
            note = ("生活道路は 01,02,11(strict) または 01,02,11,14,17(broad)。"
                    "aggregate の seikatsu 引数を使うほうが確実")
        elif field == "age":
            note = "年齢層コード。0〜24歳が最小区分で、10代のみの切り出しは不可能"
        elif field == "party_type":
            note = "コード36は2023年以前と2024年でラベルが異なるため両方を持つ"
        return {"field": field, "values": items, "note": note}

    cols = {"prefecture": "都道府県名", "road_type": "路線名",
            "road_shape": "道路形状", "weather": "天候"}
    if field not in cols:
        raise ValueError(f"未知の項目 '{field}'")
    rows = c.execute(
        f'SELECT "{cols[field]}" AS value, count(*) AS count FROM honhyo '
        f"GROUP BY 1 ORDER BY 2 DESC LIMIT 60").fetchall()
    note = ("元データは51種。北海道が方面本部別に分かれ、東京・大阪に都府が付かない。"
            "aggregate には「東京都」「北海道」でも渡せる") if field == "prefecture" else None
    return {"field": field, "values": [{"value": v, "count": n} for v, n in rows], "note": note}


@server.tool(
    title="SQLを実行する",
    description="""aggregate で表現できない集計を行うための逃げ道。読み取り専用。

テーブル名は honhyo。列名は日本語で、年齢（当事者A）のように全角括弧を含む。
文字列リテラルに似た別文字(ASCIIハイフン等)が混ざっている場合は自動で正しい
ラベルに直し、direct した内容を corrections に返す。

まず aggregate を試すこと。こちらは列名やラベルを直接扱うぶん誤りが入りやすい。""",
)
def run_sql(query: str) -> dict[str, Any]:
    c = con()
    q = query.strip().rstrip(";")
    if not re.match(r"^\s*(SELECT|WITH)\b", q, re.I):
        raise ValueError("SELECT か WITH で始まるクエリだけ実行できる")
    if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|ATTACH|COPY|INSTALL|LOAD|PRAGMA)\b", q, re.I):
        raise ValueError("読み取り専用。データを変更する構文は実行できない")

    corrections: list[dict[str, str]] = []

    def fix(m: re.Match[str]) -> str:
        lit = m.group(1)
        fixed, changed = _repair(lit)
        if changed:
            corrections.append({"before": lit, "after": fixed})
        return "'" + fixed.replace("'", "''") + "'"

    q = re.sub(r"'((?:[^']|'')*)'", fix, q)
    if "limit" not in q.lower():
        q += " LIMIT 500"

    cur = c.execute(q)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    out: dict[str, Any] = {"rows": rows, "row_count": len(rows), "sql": q}
    if corrections:
        out["corrections"] = corrections
        out["note"] = ("文字列リテラルに似た別文字が含まれていたため自動で修正した。"
                       "コード表のラベルは全角ハイフンマイナス(U+FF0D)と全角チルダ(U+FF5E)を使う")
    if not rows:
        out["note"] = ("0件。条件が厳しすぎるか、文字列リテラルの表記が"
                       "コード表と一致していない可能性がある。list_values で確認すること")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="streamable-http で待ち受ける")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    if args.http:
        server.settings.host = args.host
        server.settings.port = args.port
        server.run(transport="streamable-http")
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
