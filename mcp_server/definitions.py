# -*- coding: utf-8 -*-
"""集計の定義(生活道路・若年の歩行者と自転車)。サーバーが使う定義はここだけに置く。

絞り込みのコード、結果に付ける注記、Claude に渡す instructions とツールの説明文、
ビューの切り替えボタンは、すべてここから作る。定義を足すときにここ以外を
書き換えなくて済むようにするため。手順は CLAUDE.md の「定義を足すとき」。

コードは vocab.py(コード表から機械生成)のキー。ラベル文字列はここに書かない。
全角ハイフンマイナスと全角チルダを手で打つと、似た別文字が混ざって0件になるため。

    python mcp_server/definitions.py   # 定義ごとのコードとラベルを一覧する
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

import vocab


# ── 生活道路 ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Seikatsu:
    road_width: tuple[str, ...]  # vocab.ROAD_WIDTH のコード
    label: str                   # 見出し。ビューと表に出る
    short: str                   # 括弧書きの一言。instructions と注記に出る
    description: str             # 読むときの注意。label / short の言い換えは書かない(注記で続けて出る)


SEIKATSU: dict[str, Seikatsu] = {
    "strict": Seikatsu(
        road_width=("01", "02", "11"),
        label="strict（交差点は両方が5.5m未満）",
        short="交差する両方が5.5m未満",
        description="broad にすると件数はほぼ倍増する",
    ),
    "broad": Seikatsu(
        road_width=("01", "02", "11", "14", "17"),
        label="broad（片側のみ5.5m未満の交差点を含む）",
        short="片側のみ5.5m未満の交差点も含む",
        description="生活道路から幹線に出る出会い頭の事故がここに入る。strict のほぼ2倍になる",
    ),
}

# ツールの引数の型。SEIKATSU のキーと一致しないと import 時に落ちる
SeikatsuName = Literal["strict", "broad"]
DEFAULT_SEIKATSU: SeikatsuName = "strict"

# 定義の選び方で結果がどれだけ動くか。instructions とツールの説明文に入る
SEIKATSU_IMPACT = "strict と broad で件数が約2倍変わる"


def seikatsu_note(name: str) -> str:
    """集計結果に付ける注記。どの定義で数えたかを黙って済ませないため、必ず付ける。"""
    d = SEIKATSU[name]
    return f"生活道路 = 車道幅員5.5m未満。{name}（{d.short}）で絞った。{d.description}"


def seikatsu_choices() -> list[dict[str, str]]:
    """ビューの切り替えボタン。ボタンを HTML に書くと、定義を足したときに直し忘れる。"""
    return [{"value": k, "label": k, "title": d.label} for k, d in SEIKATSU.items()]


def seikatsu_summary() -> str:
    """instructions と説明文に入れる一覧。例: strict(交差する両方が5.5m未満)と broad(…)"""
    return "と ".join(f"{k}({d.short})" for k, d in SEIKATSU.items())


def seikatsu_codes_summary() -> str:
    """list_values の注記。例: 01,02,11(strict) または 01,02,11,14,17(broad)"""
    return " または ".join(f"{','.join(d.road_width)}({k})" for k, d in SEIKATSU.items())


# ── 若年の歩行者・自転車 ─────────────────────────────────────────────────
# 年齢は年齢層コードで、0〜24歳が最小区分。自転車は駆動補助機付(52)を含み、
# 特定小型原付(43、2024年〜)は別区分として含めない

YOUNG_AGE = ("01",)              # vocab.AGE
WALK_BIKE = ("61", "51", "52")   # vocab.PARTY_TYPE: 歩行者・自転車・駆動補助機付自転車
WALK_BIKE_NOTE = "自転車は駆動補助機付を含み、特定小型原付は含まない"


# ── 整合性の確認 ─────────────────────────────────────────────────────────
# 型とキーのずれ、vocab に無いコードは、黙って0件や型エラーになる前にここで落とす

if set(get_args(SeikatsuName)) != set(SEIKATSU):
    raise RuntimeError(f"SeikatsuName {get_args(SeikatsuName)} と SEIKATSU のキー {list(SEIKATSU)} が一致しない")
for _name, _d in SEIKATSU.items():
    if _missing := [c for c in _d.road_width if c not in vocab.ROAD_WIDTH]:
        raise RuntimeError(f"生活道路 {_name} のコード {_missing} が vocab.ROAD_WIDTH に無い")
if _missing := [c for c in YOUNG_AGE if c not in vocab.AGE] + [c for c in WALK_BIKE if c not in vocab.PARTY_TYPE]:
    raise RuntimeError(f"若年の歩行者・自転車のコード {_missing} が vocab に無い")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for name, d in SEIKATSU.items():
        print(f"{name}: {d.label}")
        for c in d.road_width:
            print(f"  {c} {' / '.join(vocab.ROAD_WIDTH[c])}")
    print("若年の歩行者・自転車:")
    for c in YOUNG_AGE:
        print(f"  年齢 {c} {' / '.join(vocab.AGE[c])}")
    for c in WALK_BIKE:
        print(f"  種別 {c} {' / '.join(vocab.PARTY_TYPE[c])}")
