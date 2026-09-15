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
from mcp.server.apps import Apps, client_supports_apps
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.types import CallToolResult, TextContent, ToolAnnotations

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import accident_map  # noqa: E402
import dashboard  # noqa: E402
import table  # noqa: E402
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


def _expand_prefecture(prefecture: list[str]) -> list[str]:
    """利用者の書いた都道府県名を、元データの51種の表記へ展開する。"""
    expanded: list[str] = []
    for p in prefecture:
        hit = _pref_map.get(p) or _pref_map.get(_repair(p)[0])
        if not hit:
            raise ValueError(f"未知の都道府県 '{p}'。list_values('prefecture') を参照")
        expanded.extend(hit)
    return expanded


# 地点の緯度経度。文字列なので毎回キャストする。空文字や範囲外は TRY_CAST で NULL になる
_LON_X = 'TRY_CAST("地点_経度（東経）_10進数" AS DOUBLE)'
_LAT_X = 'TRY_CAST("地点_緯度（北緯）_10進数" AS DOUBLE)'

# 緯度1度・経度1度のメートル換算。日本の緯度帯なら等距円筒近似で十分
# (半径50m〜数kmの用途で、測地線との差は1%に届かない)
_M_PER_DEG_LAT = 110540.0
_M_PER_DEG_LON = 111320.0


def _radius_sql(lat0: float, lon0: float, radius_m: float) -> tuple[str, str]:
    """中心からの半径で絞る条件を2つ返す(粗い矩形, 正確な距離)。

    矩形を先に置くのは row group の枝刈りを効かせるため。距離だけで書くと
    全行の三角関数を計算することになる。
    """
    import math

    dlat = radius_m / _M_PER_DEG_LAT
    dlon = radius_m / (_M_PER_DEG_LON * math.cos(math.radians(lat0)))
    box = (f"{_LAT_X} BETWEEN {lat0 - dlat:.8f} AND {lat0 + dlat:.8f} "
           f"AND {_LON_X} BETWEEN {lon0 - dlon:.8f} AND {lon0 + dlon:.8f}")
    dx = f"(({_LON_X} - {lon0:.8f}) * {_M_PER_DEG_LON} * {math.cos(math.radians(lat0)):.10f})"
    dy = f"(({_LAT_X} - {lat0:.8f}) * {_M_PER_DEG_LAT})"
    exact = f"({dx} * {dx} + {dy} * {dy}) <= {radius_m * radius_m:.4f}"
    return box, exact


def _filters(
    *,
    year_col: str = '"資料年次"',
    year_from: int | None = None,
    year_to: int | None = None,
    seikatsu: str | None = None,
    road_width: list[str] | None = None,
    prefecture: list[str] | None = None,
    party_age: list[str] | None = None,
    party_type: list[str] | None = None,
    party_scope: str = "either",
    accident_type: list[str] | None = None,
    day_night: list[str] | None = None,
    fatal_only: bool = False,
    zone30_only: bool = False,
    center_lat: float | None = None,
    center_lon: float | None = None,
    radius_m: float | None = None,
) -> tuple[list[str], list[str], str]:
    """絞り込み条件を WHERE 句のリストに組み立てる。aggregate と accident_map で共用する。

    条件の意味づけ(生活道路の定義、年齢と種別のペア判定、二重計上の回避)は
    ここ1か所に置く。ツールごとに書くと、片方だけ直して数字が食い違う。

    返すのは (WHERE句, 注記, 都道府県のラベル)。
    """
    where: list[str] = []
    notes: list[str] = []
    scope_pref = "全国"

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

    if prefecture:
        expanded = _expand_prefecture(prefecture)
        where.append(f'"都道府県名" IN ({_quote(expanded)})')
        scope_pref = "・".join(dict.fromkeys(
            "北海道" if p.startswith("北海道") else p for p in expanded))
        if any(p.startswith("北海道") for p in expanded):
            notes.append("北海道は元データが方面本部別(札幌・旭川・釧路・函館・北見)のため合算した")

    if party_age or party_type:
        # 年齢と種別は同一当事者でペア判定する。A側とB側を別々に数えて足すと、
        # 双方が条件に合う事故を二重に数えるため、OR でまとめて行単位で絞る。
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

    if radius_m is not None:
        if center_lat is None or center_lon is None:
            raise ValueError("radius_m を使うときは center_lat と center_lon も渡すこと")
        if radius_m <= 0:
            raise ValueError("radius_m は正の数")
        # 緯度経度の取り違えはよくある間違いで、黙って0件になると原因が分からない
        if not (20.0 <= center_lat <= 46.0 and 122.0 <= center_lon <= 154.0):
            raise ValueError(
                f"center_lat={center_lat} / center_lon={center_lon} が日本の範囲外。"
                "緯度(北緯、35前後)と経度(東経、139前後)を取り違えていないか確認すること")
        box, exact = _radius_sql(center_lat, center_lon, radius_m)
        where.append(box)
        where.append(exact)
        notes.append(
            f"({center_lat}, {center_lon}) から半径{radius_m:.0f}mで絞った。"
            "座標は0.1秒(緯度で約3m)刻みで記録されている")
        scope_pref = (f"半径{radius_m:.0f}m以内" if scope_pref == "全国"
                      else f"{scope_pref}／半径{radius_m:.0f}m以内")
    elif center_lat is not None or center_lon is not None:
        raise ValueError("center_lat / center_lon を使うときは radius_m も渡すこと")

    return where, notes, scope_pref


# ── MCP Apps 拡張 ───────────────────────────────────────────────────────
# 拡張はサーバーの構築時に取り込まれるため、ui:// リソースの登録と
# @apps.tool の定義は MCPServer(...) より前に置く必要がある。
#
# ビューは Claude Desktop / claude.ai のようなサンドボックスiframeを持つ
# ホストでのみ描画される。ターミナルの Claude Code では描画されないが、
# ツール自体は同じ数字を返すので、集計として壊れることはない。

apps = Apps()

apps.add_html_resource(
    dashboard.RESOURCE_URI,
    dashboard.load_html(),
    name="seikatsu_dashboard",
    title="生活道路ダッシュボード",
    description="生活道路（車道幅員5.5m未満）の事故の経年推移。strict/broad をその場で切り替えられる",
    prefers_border=True,
)

# 地図ビューだけは外部と通信する。宣言したドメイン以外への接続はホストのCSPが止める
apps.add_html_resource(
    accident_map.RESOURCE_URI,
    accident_map.load_html(),
    name="accident_map",
    title="事故地点マップ",
    description="絞り込んだ事故の発生地点を地理院ベクトルタイル(淡色)の上に描く地図",
    csp=accident_map.CSP,
    prefers_border=True,
)

# 集計表。外部とは通信しないので CSP の宣言は要らない
apps.add_html_resource(
    table.RESOURCE_URI,
    table.load_html(),
    name="aggregate_table",
    title="集計表",
    description="aggregate の結果を表として描く。構成比と指数を併記し、2次元なら行列に畳む",
    prefers_border=True,
)

# 0〜24歳の歩行者・自転車。自転車は電動アシストを含み、特定小型原付(43)は別区分として含めない
_YOUNG_AGE = vocab.AGE["01"]
_WALK_BIKE = vocab.PARTY_TYPE["61"] + vocab.PARTY_TYPE["51"] + vocab.PARTY_TYPE["52"]


def _young_walk_bike_sql() -> str:
    """当事者AまたはBが「0〜24歳の歩行者・自転車」である条件。

    年齢と種別は同一当事者でペア判定する。A側・B側を別々に数えて足すと、
    双方が該当する事故を二重に数えるため、FILTER に入れて行単位で数える。
    """
    age, kind = _quote(_YOUNG_AGE), _quote(_WALK_BIKE)
    return "(" + " OR ".join(
        f'("年齢（当事者{s}）" IN ({age}) AND "当事者種別（当事者{s}）" IN ({kind}))'
        for s in ("A", "B")) + ")"


def _summary_md(p: dict[str, Any]) -> str:
    """モデルに渡すテキスト。ビューが描画されない環境ではこれがそのまま答えになる。

    構造化データ(structuredContent)をそのまま会話に流すとJSONの壁になるので、
    読める表と注記だけを渡す。ビューは structuredContent を見るので影響しない。
    """
    t = p["totals"]
    rows = "\n".join(
        f'| {r["年"]} | {r["件数"]:,} | {r["指数"]:.0f} | {r["構成比"]*100:.1f}% | '
        f'{r["死亡事故"]:,} | {r["若年歩行者自転車"]:,} | {r["ゾーン30"]:,} |'
        for r in p["years"])
    return (
        f'## 生活道路の事故\n\n'
        f'{p["scope"]}／{p["definition"]["label"]}\n\n'
        f'| 年 | 件数 | 指数 | 全事故比 | 死亡事故 | 0〜24歳 歩行者・自転車 | ゾーン30 |\n'
        f'|---:|---:|---:|---:|---:|---:|---:|\n{rows}\n\n'
        f'期間合計 {t["件数"]:,}件（全事故 {t["全事故件数"]:,}件の {t["構成比"]*100:.1f}%）／'
        f'死亡事故 {t["死亡事故"]:,}件・死者 {t["死者数"]:,}人／'
        f'0〜24歳の歩行者・自転車が関与 {t["若年歩行者自転車"]:,}件（{t["若年構成比"]*100:.1f}%）／'
        f'ゾーン30内 {t["ゾーン30"]:,}件（{t["ゾーン30構成比"]*100:.1f}%）\n\n'
        + "\n".join("- " + n for n in p["notes"])
        + f'\n\n<details><summary>SQL</summary>\n\n```sql\n{p["sql"]}\n```\n</details>'
    )


_SEIKATSU_DESC = {
    "strict": "交差点は交差する両方の道路が5.5m未満のものだけを数える。"
              "broad にすると件数はほぼ倍増する",
    "broad": "片側のみ5.5m未満の交差点も含める。"
             "生活道路から幹線に出る出会い頭の事故がここに入る。strict のほぼ2倍になる",
}


@apps.tool(
    resource_uri=dashboard.RESOURCE_URI,
    visibility=["model", "app"],
    title="生活道路ダッシュボード",
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                idempotent_hint=True, open_world_hint=False),
    description="""生活道路（車道幅員5.5m未満）の事故を年次別にまとめ、対話的なダッシュボードとして表示する。

「生活道路の事故はどうなっているか」「生活道路の推移を見せて」のような
概況の問いにはこれを使う。aggregate より先に試してよい。

全事故（母数）を同じクエリで一緒に数えるので、生活道路の減少が全体の減少と
同じなのか、それより速い/遅いのかがそのまま読める。

seikatsu の strict / broad は件数を約2倍動かす。既定は strict。
ビュー上のトグルでも切り替えられるので、迷ったら strict のまま出して利用者に選ばせてよい。

返り値の years に年次別の件数・指数・構成比、totals に期間合計、notes に
読むときの注意、sql に実行したSQLが入る。ビューが描画されない環境でも
この数字だけで表を書ける。""",
)
def seikatsu_dashboard(
    ctx: Context,
    seikatsu: Literal["strict", "broad"] = "strict",
    year_from: int = 2019,
    year_to: int = 2024,
    prefecture: list[str] | None = None,
) -> CallToolResult:
    c = con()
    if year_from > year_to:
        raise ValueError("year_from が year_to より大きい")

    # ビューが描画されるのは、クライアントが io.modelcontextprotocol/ui を
    # ネゴシエートしたときだけ。していない相手には数字だけを返し、注記で伝える。
    ui_ok = client_supports_apps(ctx)

    width_labels = _codes_to_labels(SEIKATSU[seikatsu], vocab.ROAD_WIDTH, "road_width")
    w = f'"車道幅員" IN ({_quote(width_labels)})'
    young = _young_walk_bike_sql()

    # 年次は資料年次(計上年)で固定する。発生年で数えると最新年が約3%過少に出て、
    # 実際の減少と区別がつかなくなるため、推移を見るこのビューでは選ばせない。
    where = [f'"資料年次" >= {int(year_from)}', f'"資料年次" <= {int(year_to)}']
    notes: list[str] = []
    scope_pref = "全国"
    if prefecture:
        expanded = _expand_prefecture(prefecture)
        where.append(f'"都道府県名" IN ({_quote(expanded)})')
        scope_pref = "・".join(dict.fromkeys(
            "北海道" if p.startswith("北海道") else p for p in expanded))
        if any(p.startswith("北海道") for p in expanded):
            notes.append("北海道は元データが方面本部別(札幌・旭川・釧路・函館・北見)のため合算した")

    sql = (
        'SELECT "資料年次" AS 年,\n'
        "       count(*) AS 全事故件数,\n"
        f"       count(*) FILTER (WHERE {w}) AS 件数,\n"
        f'       sum(CAST("死者数" AS INTEGER)) FILTER (WHERE {w}) AS 死者数,\n'
        f'       sum(CAST("負傷者数" AS INTEGER)) FILTER (WHERE {w}) AS 負傷者数,\n'
        f"       count(*) FILTER (WHERE {w} AND \"事故内容\" = '死亡事故') AS 死亡事故,\n"
        f"       count(*) FILTER (WHERE {w} AND {young}) AS 若年歩行者自転車,\n"
        f"       count(*) FILTER (WHERE {w} AND \"ゾーン規制\" = 'ゾーン30') AS ゾーン30\n"
        "FROM honhyo\n"
        "WHERE " + "\n  AND ".join(where) + "\n"
        "GROUP BY 1\n"
        "ORDER BY 1"
    )

    cur = c.execute(sql)
    cols = [d[0] for d in cur.description]
    years = [dict(zip(cols, r)) for r in cur.fetchall()]
    if not years:
        raise ValueError(f"{year_from}〜{year_to}年に該当する行がない。年やprefectureの指定を確認すること")

    base, base_all = years[0]["件数"] or 1, years[0]["全事故件数"] or 1
    for r in years:
        for k in ("件数", "全事故件数", "死者数", "負傷者数", "死亡事故", "若年歩行者自転車", "ゾーン30"):
            r[k] = int(r[k] or 0)
        r["指数"] = round(r["件数"] / base * 100, 1)
        r["全事故指数"] = round(r["全事故件数"] / base_all * 100, 1)
        r["構成比"] = round(r["件数"] / r["全事故件数"], 5) if r["全事故件数"] else 0.0
        r["若年構成比"] = round(r["若年歩行者自転車"] / r["件数"], 5) if r["件数"] else 0.0

    totals = {k: sum(r[k] for r in years) for k in
              ("全事故件数", "件数", "死者数", "負傷者数", "死亡事故", "若年歩行者自転車", "ゾーン30")}
    n = totals["件数"] or 1
    totals["構成比"] = round(totals["件数"] / (totals["全事故件数"] or 1), 5)
    totals["若年構成比"] = round(totals["若年歩行者自転車"] / n, 5)
    totals["ゾーン30構成比"] = round(totals["ゾーン30"] / n, 5)

    notes.append(f"生活道路 = 車道幅員5.5m未満。{seikatsu}（{_SEIKATSU_DESC[seikatsu]}）")
    notes.append("資料年次(計上年)で集計した。各年の全事故件数は警察庁公表値と一致する")
    notes.append("実数だけで語らないこと。全事故の指数(破線)と比べて初めて意味を持つ。"
                 "2020年はコロナ禍で全体が前年比19%減している")
    notes.append("0〜24歳は年齢層コードの最小区分。10代のみ・20代のみの切り出しはできない")
    notes.append("歩行者・自転車は当事者AまたはBで年齢と種別をペア判定し、行単位で1件と数えた"
                 "(二重計上なし)。自転車は駆動補助機付を含み、特定小型原付は含まない")
    if min(r["死亡事故"] for r in years) < 50:
        notes.append("死亡事故は年あたり数十件規模。ここからさらに絞るとトレンドとしては読めない")
    notes.append("ゾーン30の件数の増減から規制の効果は判定できない。ゾーン30の指定区域自体が"
                 "年々拡大しているため、母数が動いている")
    notes.append("ゾーン規制は「ゾーン30」「規制なし」の2値しかない。ハンプ・狭さく等を伴う"
                 "ゾーン30プラス(2021年度〜)は区別できず、物理デバイスの有無も本票にはない")
    if not ui_ok:
        notes.append("このクライアントは MCP Apps を有効にしていないため、ダッシュボードは"
                     "描画されない。上の years / totals をそのまま表にして示すこと")

    payload = {
        "scope": f"{year_from}〜{year_to}年・{scope_pref}・資料年次(計上年)ベース",
        "definition": {
            "seikatsu": seikatsu,
            "label": "strict（交差点は両方が5.5m未満）" if seikatsu == "strict"
                     else "broad（片側のみ5.5m未満の交差点を含む）",
            "description": _SEIKATSU_DESC[seikatsu],
            "road_width_labels": width_labels,
        },
        "args": {"seikatsu": seikatsu, "year_from": year_from,
                 "year_to": year_to, "prefecture": prefecture},
        "years": years,
        "totals": totals,
        "notes": notes,
        "sql": sql,
    }
    # content はモデルが読む表、structured_content はビューが読むデータ。
    # 分けないと、ビューが描画されたときに同じ数字が二重に会話へ流れる。
    return CallToolResult(
        content=[TextContent(type="text", text=_summary_md(payload))],
        structured_content=payload,
    )


# 日本の外に落ちた座標を弾くための範囲。0 や空文字が DOUBLE で 0.0 になるのを止める
_JP_BBOX = {"lon": (122.0, 154.0), "lat": (20.0, 46.0)}
_MAX_POINTS_CAP = 20000


def _view_bounds(points: list[list[float]]) -> list[float]:
    """初期表示の範囲。外れ値1%を落として決める。

    東京のように離島を含む都道府県だと、最小最大でくくった途端に本土が豆粒になる。
    落とした点も描かれてはいるので、引けば見える。
    """
    def span(i: int) -> tuple[float, float]:
        v = sorted(p[i] for p in points)
        k = len(v) // 100
        return (v[k], v[-1 - k]) if len(v) >= 200 else (v[0], v[-1])

    (w, e), (s, n) = span(0), span(1)
    return [w, s, e, n]


def _circle_bounds(lat0: float, lon0: float, radius_m: float) -> list[float]:
    """半径指定のときの初期表示範囲。点の分布ではなく指定した円から決める。

    点から決めると、円の端に1件しかない場合にそこまで引きの絵になり、
    「半径50mを見ている」という指定が画面に出なくなる。少しだけ広げて円が収まるようにする。
    """
    import math

    pad = 1.25
    dlat = radius_m * pad / _M_PER_DEG_LAT
    dlon = radius_m * pad / (_M_PER_DEG_LON * math.cos(math.radians(lat0)))
    return [lon0 - dlon, lat0 - dlat, lon0 + dlon, lat0 + dlat]


def _map_summary_md(p: dict[str, Any]) -> str:
    """モデルに渡すテキスト。地図そのものは読めないので、件数と注意書きを渡す。"""
    c = p["counts"]
    line = f'該当 {c["該当"]:,}件のうち {c["描画"]:,}件を地図に描いた'
    if c["抽出"]:
        line += "（無作為抽出）"
    return (
        f'## 事故地点マップ\n\n{p["scope"]}\n\n{line}。'
        f'座標が使えなかったのは {c["座標なし"]:,}件。\n\n'
        + "\n".join("- " + n for n in p["notes"])
        + f'\n\n<details><summary>SQL</summary>\n\n```sql\n{p["sql"]}\n```\n</details>'
    )


@apps.tool(
    resource_uri=accident_map.RESOURCE_URI,
    visibility=["model", "app"],
    # 関数名は accident_map モジュールと衝突するので _tool 付き。公開名はここで固定する
    name="accident_map",
    title="事故地点マップ",
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                idempotent_hint=True, open_world_hint=False),
    description="""絞り込んだ事故の発生地点を地図に描く。「どこで起きているか」を見るためのツール。

条件の指定は aggregate と同じコード値で行う（party_age, party_type, seikatsu ほか）。
「どこ」を問われたときに使い、「いくつ・どう増えた」は aggregate で数えること。

点の数が max_points を超えると無作為抽出して描く。抽出は REPEATABLE で固定して
あるので同じ条件なら同じ点が出るが、**描画件数を事故件数として語らないこと**。
件数は返り値の counts.該当 を使う。

全国を無条件で描くと密度の濃淡しか見えない。都道府県や市区、条件で絞ってから使う。

特定の地点まわりを見るときは center_lat / center_lon / radius_m の3つを揃えて渡す
（例: 交差点の半径50m）。3つとも要る。座標は利用者が指定するもので、
このサーバーは地名から座標を引く機能を持たない。地名しか分からない場合は、
座標を確かめてもらうこと。

座標は0.1秒(緯度で約3m)刻みで記録されているので、半径50m程度の指定には耐える。
ただし記録された地点そのものの正確さは別問題で、交差点の中心に寄せられている
とは限らない。道路形状の「交差点－」「交差点付近－」と併せて読むこと。""",
)
def accident_map_tool(
    ctx: Context,
    prefecture: list[str] | None = None,
    year_from: int = 2019,
    year_to: int = 2024,
    seikatsu: Literal["strict", "broad"] | None = None,
    road_width: list[str] | None = None,
    party_age: list[str] | None = None,
    party_type: list[str] | None = None,
    party_scope: Literal["A", "B", "either"] = "either",
    accident_type: list[str] | None = None,
    day_night: list[str] | None = None,
    fatal_only: bool = False,
    zone30_only: bool = False,
    center_lat: float | None = None,
    center_lon: float | None = None,
    radius_m: float | None = None,
    max_points: int = 5000,
) -> CallToolResult:
    c = con()
    if year_from > year_to:
        raise ValueError("year_from が year_to より大きい")
    max_points = max(100, min(int(max_points), _MAX_POINTS_CAP))
    ui_ok = client_supports_apps(ctx)

    # 年次は資料年次(計上年)。発生年で絞ると最新年だけ約3%欠ける
    where, notes, scope_pref = _filters(
        year_from=year_from, year_to=year_to, seikatsu=seikatsu, road_width=road_width,
        prefecture=prefecture, party_age=party_age, party_type=party_type,
        party_scope=party_scope, accident_type=accident_type, day_night=day_night,
        fatal_only=fatal_only, zone30_only=zone30_only,
        center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)

    lon_x = 'TRY_CAST("地点_経度（東経）_10進数" AS DOUBLE)'
    lat_x = 'TRY_CAST("地点_緯度（北緯）_10進数" AS DOUBLE)'
    inner = (
        f"  SELECT {lon_x} AS lon,\n"
        f"         {lat_x} AS lat,\n"
        '         "資料年次" AS 年, "事故内容", "事故類型",\n'
        '         "当事者種別（当事者A）" AS 種別A, "当事者種別（当事者B）" AS 種別B,\n'
        '         "車道幅員", "昼夜", "ゾーン規制",\n'
        f"         {PREF_EXPR} AS 都道府県\n"
        "  FROM honhyo\n"
        + ("  WHERE " + "\n    AND ".join(where) + "\n" if where else ""))
    ok = (f'lon BETWEEN {_JP_BBOX["lon"][0]} AND {_JP_BBOX["lon"][1]} '
          f'AND lat BETWEEN {_JP_BBOX["lat"][0]} AND {_JP_BBOX["lat"][1]}')

    matched, no_coord = c.execute(
        f"WITH f AS (\n{inner})\n"
        f"SELECT count(*) FILTER (WHERE {ok}), count(*) FILTER (WHERE NOT ({ok}) OR lon IS NULL)\n"
        "FROM f").fetchone()
    matched, no_coord = int(matched or 0), int(no_coord or 0)
    if matched == 0:
        raise ValueError(
            "条件に合う事故が0件（座標のある行が無い）。条件を緩めるか、"
            "aggregate で件数を確かめること")

    sampled = matched > max_points
    # 行の内容のハッシュ順に上位を採る。同じ条件なら毎回同じ点が出る。
    # USING SAMPLE ... REPEATABLE は並列スキャンだと再現しない（実測で毎回違う点が返る）。
    sample_sql = (f"ORDER BY hash(lon, lat, 年, 種別A, 種別B, 昼夜)\nLIMIT {max_points}\n"
                  if sampled else "")
    sql = (f"WITH f AS (\n{inner})\n"
           f"SELECT * FROM f\nWHERE {ok}\n{sample_sql}")

    cur = c.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    # 点はオブジェクトではなく配列で返す。5,000点だとキー名だけで数百KBになる。
    legend: dict[str, list[str]] = {"事故類型": [], "種別": [], "車道幅員": [], "昼夜": [], "都道府県": []}

    def idx(kind: str, value: str | None) -> int:
        v = value or "不明"
        arr = legend[kind]
        if v not in arr:
            arr.append(v)
        return arr.index(v)

    points = [[round(r["lon"], 5), round(r["lat"], 5), int(r["年"]),
               1 if r["事故内容"] == "死亡事故" else 0,
               idx("事故類型", r["事故類型"]), idx("種別", r["種別A"]), idx("種別", r["種別B"]),
               idx("車道幅員", r["車道幅員"]), idx("昼夜", r["昼夜"]),
               1 if r["ゾーン規制"] == "ゾーン30" else 0, idx("都道府県", r["都道府県"])]
              for r in rows]

    notes.append("資料年次(計上年)で絞った。地図上の点は事故1件の発生地点")
    if sampled:
        notes.append(f"該当 {matched:,}件は多いため {max_points:,}件を抽出して描いた"
                     "(内容のハッシュ順。同じ条件なら同じ点が出る)。密度の見え方は保たれるが、"
                     "描画件数を事故件数として語らないこと")
    if no_coord:
        notes.append(f"座標が範囲外・欠損の {no_coord:,}件は描いていない")
    notes.append("点の重なりは件数の多さを意味しない。同一地点の複数事故は重なって1点に見える")
    if not ui_ok:
        notes.append("このクライアントは MCP Apps を有効にしていないため地図は描画されない。"
                     "地点を見せる必要があるなら、対応ホスト(Claude Desktop 等)で開くこと")

    payload = {
        "scope": f"{year_from}〜{year_to}年・{scope_pref}・資料年次(計上年)ベース",
        "args": {"prefecture": prefecture, "year_from": year_from, "year_to": year_to,
                 "seikatsu": seikatsu, "road_width": road_width,
                 "party_age": party_age, "party_type": party_type, "party_scope": party_scope,
                 "accident_type": accident_type, "day_night": day_night,
                 "fatal_only": fatal_only, "zone30_only": zone30_only,
                 "max_points": max_points},
        "counts": {"該当": matched, "描画": len(points), "抽出": sampled, "座標なし": no_coord},
        "fields": ["lon", "lat", "年", "死亡", "事故類型", "種別A", "種別B",
                   "車道幅員", "昼夜", "ゾーン30", "都道府県"],
        "legend": legend,
        "points": points,
        "bounds": _circle_bounds(center_lat, center_lon, radius_m) if radius_m else _view_bounds(points),
        # 既定の15は、点がたまたま一箇所に固まったときに街路レベルまで寄るのを防ぐため。
        # 半径を明示されたときは、その範囲を見たいという指定なので上限を上げる
        "max_zoom": 18 if radius_m else 15,
        "notes": notes,
        "sql": sql,
    }
    return CallToolResult(
        content=[TextContent(type="text", text=_map_summary_md(payload))],
        structured_content=payload,
    )


# 改行。ソースに直接書くとツール経由の編集で潰れやすいので定数にしている
NL = chr(10)

# 集計表の指標列。これ以外の列は group_by のキーとして扱う
_MEASURES = ("件数", "死者数", "負傷者数")

_GROUP_LABEL = {
    "year": "年", "month": "月", "prefecture": "都道府県", "police_station": "警察署",
    "road_width": "車道幅員", "road_type": "路線", "road_shape": "道路形状",
    "zone": "ゾーン規制", "accident_type": "事故類型", "accident_content": "事故内容",
    "day_night": "昼夜", "weather": "天候", "age_a": "年齢A", "age_b": "年齢B",
    "party_type_a": "当事者種別A", "party_type_b": "当事者種別B",
}


def _agg_scope(scope_pref: str, year_basis: str, year_from: int | None,
               year_to: int | None, seikatsu: str | None, fatal_only: bool,
               zone30_only: bool, group_by: list[str]) -> str:
    """ビューの見出しに出す、何をどう絞ったかの一行。"""
    span = ("全期間" if year_from is None and year_to is None
            else f"{year_from or 2019}〜{year_to or 2024}年")
    parts = [scope_pref, f"{span}（{year_basis}）"]
    if seikatsu:
        parts.append(f"生活道路 {seikatsu}")
    if fatal_only:
        parts.append("死亡事故のみ")
    if zone30_only:
        parts.append("ゾーン30内のみ")
    axes = " × ".join(_GROUP_LABEL.get(g, g) for g in group_by)
    return " / ".join(parts) + f" ・ {axes}別"


def _table_md(p: dict[str, Any]) -> str:
    """モデルに渡すテキスト。ビューが描画されない環境ではこれがそのまま答えになる。

    件数だけを並べると母数の変化を無視した読み方になるので、構成比を必ず併記し、
    年だけで切った集計では指数(基準年=100)も出す。
    """
    keys, rows = p["key_columns"], p["rows"]
    total = p["sum_count"]
    # 指数は「年だけで切った」ときにしか意味を持たない。
    # 年×都道府県のように同じ年が複数行あると、基準年の件数が定まらない。
    base = None
    if keys == ["年"] and rows:
        base = int(min(rows, key=lambda r: int(r["年"]))["件数"])

    head = keys + ["件数", "構成比"] + (["指数"] if base else [])         + [m for m in p["measures"] if m != "件数"]
    align = ["---" if k in keys else "---:" for k in head]

    body = []
    for r in rows:
        cells = [str(r[k]) for k in keys]
        cells.append(f'{int(r["件数"]):,}')
        cells.append(f'{int(r["件数"]) / total * 100:.1f}%' if total else "-")
        if base:
            cells.append(f'{int(r["件数"]) / base * 100:.0f}')
        cells += [f'{int(r[m]):,}' for m in p["measures"] if m != "件数"]
        body.append("| " + " | ".join(cells) + " |")

    denom = "返した行の合計に対する比" if p["truncated"] else "この集計の合計に対する比"
    head_md = '| ' + ' | '.join(head) + ' |'
    align_md = '| ' + ' | '.join(align) + ' |'
    return (
        f'## 集計{NL}{NL}' + p['scope'] + NL + NL
        + head_md + NL + align_md + NL + NL.join(body) + NL + NL
        + f'{p["row_count"]}行／件数計 {total:,}（構成比は{denom}）' + NL + NL
        + NL.join('- ' + n for n in p['notes'])
        + NL + NL + '<details><summary>SQL</summary>' + NL + NL
        + '```sql' + NL + p['sql'] + NL + '```' + NL + '</details>'
    )


@apps.tool(
    resource_uri=table.RESOURCE_URI,
    visibility=["model", "app"],
    title="集計する",
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                idempotent_hint=True, open_world_hint=False),
    description="""交通事故を条件で絞り込んで集計する。主にこれを使う。

引数はラベル文字列ではなくコード値で指定する(例: 車道幅員なら '01','02','11')。
有効なコードは list_values で確認できる。

生活道路を見るときは seikatsu='strict' または 'broad' を使う。
road_width を直接指定するより意図が明確になる。

年齢と当事者種別を同時に指定すると、同一当事者でのペア判定になる。
party_scope='either' なら「AまたはBがその年齢かつその種別」の事故を行単位で数える。

よく使うコードは以下。これで足りる場合 list_values を呼ぶ必要はない。

  party_age    01=0〜24歳  25=25〜34  35=35〜44  45=45〜54
               55=55〜64   65=65〜74  75=75歳以上  00=不明
  party_type   61=歩行者  51=自転車  52=電動アシスト自転車
               36=原付  35=原付二種  31〜34=自動二輪
               03=乗用車普通  04=軽自動車  01=乗用車大型  02=乗用車中型
               13=貨物普通  14=貨物軽  43=特定小型原付(2024〜)
  accident_type 01=人対車両  21=車両相互  41=車両単独  61=列車
  day_night    昼は 11(明) 12(昼) 13(暮)、夜は 21(暮) 22(夜) 23(明) の6区分。
               「昼間」なら ['11','12','13']、「夜間」なら ['21','22','23'] を渡す

  group_by     year, month, prefecture, police_station, road_width, road_type,
               road_shape, zone, accident_type, accident_content, day_night,
               weather, age_a, age_b, party_type_a, party_type_b

都道府県は prefecture に日本語名で渡す（「東京都」「東京」「北海道」いずれも可）。

順序は既定で、年や月を含むときはキー順、それ以外は件数の多い順。
limit で上位を絞るときは件数順が使われるので順位を誤らない。

返り値には実行したSQLが含まれる。数字に疑問があれば確認すること。""",
)
def aggregate(
    ctx: Context,
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
            # 列名は日本語に揃える。year だけ 年 で他が英語だと、表の見出しが
            # 「年 / prefecture」のように混ざって読みにくい
            selects.append(f'{GROUP_COLUMNS[g]} AS "{_GROUP_LABEL.get(g, g)}"')
            groups.append(GROUP_COLUMNS[g])
        else:
            raise ValueError(f"group_by に未知の項目 '{g}'。使えるのは {sorted(GROUP_COLUMNS)}")

    where, filter_notes, scope_pref = _filters(
        year_col=year_col, year_from=year_from, year_to=year_to,
        seikatsu=seikatsu, road_width=road_width, prefecture=prefecture,
        party_age=party_age, party_type=party_type, party_scope=party_scope,
        accident_type=accident_type, day_night=day_night,
        fatal_only=fatal_only, zone30_only=zone30_only)
    notes += filter_notes
    if year_basis == "発生年":
        notes.append("発生年で集計した。最新年は翌年ファイルに計上される分が欠けるため約3%過少に出る")

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

    truncated = len(rows) >= int(limit)
    if truncated:
        notes.append(f"limit {int(limit)} に達している。返していない行がある")
    if not client_supports_apps(ctx):
        notes.append("このクライアントは表ビューに対応していないので数字だけを返した")

    payload = {
        "scope": _agg_scope(scope_pref, year_basis, year_from, year_to,
                            seikatsu, fatal_only, zone30_only, group_by),
        "key_columns": [c for c in cols if c not in _MEASURES],
        "measures": [m for m in _MEASURES if m in cols],
        "rows": rows,
        "row_count": len(rows),
        "sum_count": sum(int(r["件数"]) for r in rows),
        "truncated": truncated,
        "notes": notes,
        "sql": sql,
    }
    return CallToolResult(
        content=[TextContent(type="text", text=_table_md(payload))],
        structured_content=payload,
    )


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

7. 生活道路の概況を聞かれたら seikatsu_dashboard を使う。全事故(母数)を同時に数え、
   対応ホストではグラフ付きのビューが出る。細かい切り口が要るときだけ aggregate に降りる。

実数の増減だけで語らないこと。2020年はコロナ禍で全体件数が前年比19%減しており、
母数の変化を無視すると傾向を読み誤る。構成比や指数を併せて見ること。""",
    extensions=[apps],
)


@server.tool(
    title="コード値を調べる",
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                idempotent_hint=True, open_world_hint=False),
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
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                idempotent_hint=True, open_world_hint=False),
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
    ap.add_argument("--allow-host", action="append", default=[],
                    help="Hostヘッダを許可するホスト名。トンネルや独自ドメインで公開するとき必要。"
                         "複数指定可。'*' で検証を無効化する(公開時は非推奨)")
    args = ap.parse_args()
    if args.http:
        import uvicorn
        from mcp.server.transport_security import TransportSecuritySettings

        # DNSリバインディング対策で Host ヘッダが検証される。既定は localhost のみ許可。
        # トンネルや独自ドメイン越しに公開するときは、そのホスト名を渡す必要がある。
        hosts = [f"127.0.0.1:{args.port}", f"localhost:{args.port}", *args.allow_host]
        sec = TransportSecuritySettings(
            enable_dns_rebinding_protection="*" not in args.allow_host,
            allowed_hosts=hosts,
            allowed_origins=["*"] if "*" in args.allow_host
            else [f"https://{h}" for h in args.allow_host],
        )
        con()  # 起動時に接続を張り、Parquetのフッタを読んでおく
        print(f"MCP endpoint: http://{args.host}:{args.port}/mcp", file=sys.stderr)
        if args.allow_host:
            print(f"allowed hosts: {args.allow_host}", file=sys.stderr)
        uvicorn.run(server.streamable_http_app(transport_security=sec),
                    host=args.host, port=args.port, log_level="warning")
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
