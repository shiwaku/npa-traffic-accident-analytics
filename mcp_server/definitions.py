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
    ja: str                      # 日本語の呼び名。label は「strict（厳密）」のように組み立てる
    includes: str                # 何を含めるか。初めて見る人が読んで分かる言葉で書く
    impact: str                  # もう一方と比べてどう違うか

    def label(self, name: str) -> str:
        return f"{name}（{self.ja}）"


# 定義を1つだけ見せられても、なぜ2通りあるのかが分からない。注記には毎回これを先に出す
SEIKATSU_INTRO = ("生活道路は車道幅員5.5m未満の道路。交差点は2本の道路が交わるため、"
                  "片方だけが細い交差点を含めるかどうかで数え方が2通りある")

SEIKATSU: dict[str, Seikatsu] = {
    "strict": Seikatsu(
        road_width=("01", "02", "11"),
        ja="狭義",
        includes="5.5m未満の単路と、交わる2本とも5.5m未満の交差点だけを数える",
        impact="broad にすると件数は約1.8倍になる",
    ),
    "broad": Seikatsu(
        road_width=("01", "02", "11", "14", "17"),
        ja="広義",
        includes="strict に加えて、片方だけ5.5m未満の交差点（細い道と5.5m以上の道の交差点）も数える",
        impact="生活道路から幹線に出たところの出会い頭事故などが加わり、strict の約1.8倍になる",
    ),
}

# ツールの引数の型。SEIKATSU のキーと一致しないと import 時に落ちる
SeikatsuName = Literal["strict", "broad"]
DEFAULT_SEIKATSU: SeikatsuName = "strict"

# どちらも公表値の算出方法を再現したものではない。「警察庁の定義に準拠」と言わせないため
# instructions に入れる。国交省は令和4年の生活道路の事故を約7万件としているが、
# 同じ年のこのデータは strict 49,140件・broad 88,667件でどちらとも合わない
# (幹線道路21万件と合わせた28万件は、全件から「一般交通の場所」を除いた数と一致する)
SEIKATSU_OFFICIAL = ("警察庁・国交省の資料は生活道路を「車道幅員5.5m未満の道路」とするが、"
                     "交差点の扱いは公表されておらず、strict・broad のどちらも公表値とは一致しない"
                     "(国交省の令和4年 約7万件に対し strict 4.9万件・broad 8.9万件)。"
                     "どちらかを「公式の定義に準拠」と説明しないこと")

# 定義の選び方で結果がどれだけ動くか。instructions とツールの説明文に入る
# (全期間 strict 312,035件 → broad 558,591件)
SEIKATSU_IMPACT = "broad は strict の約1.8倍の件数になる"


def seikatsu_label(name: str) -> str:
    return SEIKATSU[name].label(name)


def seikatsu_note(name: str) -> str:
    """集計結果に付ける注記。どの定義で数えたかを黙って済ませないため、必ず付ける。

    使った定義だけでなく全部の定義を並べる。片方しか書かないと、
    もう一方が何を指すのか、なぜ選べるのかが初めての人に伝わらない。
    """
    all_defs = "／".join(f"{d.label(k)}: {d.includes}" for k, d in SEIKATSU.items())
    return (f"{SEIKATSU_INTRO}（{all_defs}）。"
            f"この集計は {seikatsu_label(name)} で数えた。{SEIKATSU[name].impact}")


def seikatsu_choices() -> list[dict[str, str]]:
    """ビューの切り替えボタン。ボタンを HTML に書くと、定義を足したときに直し忘れる。"""
    return [{"value": k, "label": d.label(k), "title": d.includes} for k, d in SEIKATSU.items()]


def seikatsu_summary() -> str:
    """instructions と説明文に入れる一覧。例: strict（厳密）: …／broad（広義）: …"""
    return "／".join(f"{d.label(k)}: {d.includes}" for k, d in SEIKATSU.items())


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
        print(f"{name}: {d.label(name)}　{d.includes}")
        for c in d.road_width:
            print(f"  {c} {' / '.join(vocab.ROAD_WIDTH[c])}")
    print("若年の歩行者・自転車:")
    for c in YOUNG_AGE:
        print(f"  年齢 {c} {' / '.join(vocab.AGE[c])}")
    for c in WALK_BIKE:
        print(f"  種別 {c} {' / '.join(vocab.PARTY_TYPE[c])}")
