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
    label: str                   # 使う人に見せる名前。含める道路をそのまま書く。キー(strict など)は見せない
    includes: str                # 何を含めるか。初めて見る人が読んで分かる言葉で書く
    impact: str                  # もう一方と比べてどう違うか


# 定義を1つだけ見せられても、なぜ2通りあるのかが分からない。注記には毎回これを先に出す
SEIKATSU_INTRO = ("生活道路は車道幅員5.5m未満の道路。交差点は2本の道路が交わるため、"
                  "片方だけが5.5m未満の交差点を含めるかどうかで数え方が2通りある")

SEIKATSU: dict[str, Seikatsu] = {
    "strict": Seikatsu(
        road_width=("01", "02", "11"),
        label="5.5m未満の道と、5.5m未満どうしの交差点",
        includes="5.5m未満の単路と、交わる2本とも5.5m未満の交差点を数える",
        impact="片方だけ5.5m未満の交差点も数えると、件数は約1.8倍になる",
    ),
    "broad": Seikatsu(
        road_width=("01", "02", "11", "14", "17"),
        label="5.5m未満の道と、5.5m未満の道が1本以上交わる交差点",
        includes="5.5m未満の単路と、交わる2本のうち1本以上が5.5m未満の交差点を数える",
        impact="片方だけ5.5m未満の交差点（5.5m未満の道から5.5m以上の道に出る交差点）の事故が加わり、"
               "件数はもう一方の約1.8倍になる",
    ),
}

# ツールの引数の型。SEIKATSU のキーと一致しないと import 時に落ちる
SeikatsuName = Literal["strict", "broad"]
DEFAULT_SEIKATSU: SeikatsuName = "strict"

# 公表資料との関係。「警察庁の定義に準拠」と言わせないため instructions に入れる。
# 国交省・警察庁の地図化マニュアル(令和7年7月)p.11 は車道幅員コード 1・2・11・14・17 を
# 生活道路として抽出させており、broad と同じ範囲。一方、警察庁の公表値「5.5m未満道路の
# 交通事故」は2024年 67,522件で、同年のこのデータは strict 45,296件・broad 83,237件と
# どちらとも合わない(全事故 290,895件は一致する)
SEIKATSU_OFFICIAL = ("警察庁・国交省の資料は生活道路を「車道幅員5.5m未満の道路」とする。"
                     "国交省・警察庁の地図化マニュアル(令和7年7月)は broad と同じ車道幅員コードで"
                     "生活道路を抽出しているので、broad は「地図化マニュアルの抽出条件と同じ」と言ってよい。"
                     "ただし警察庁の公表件数は strict・broad のどちらとも一致しない"
                     "(2024年の公表値 67,522件に対し strict 45,296件・broad 83,237件)。"
                     "strict を「警察庁の定義に準拠」と説明しないこと。"
                     "どちらも「公表件数を再現したもの」と説明しないこと")

# 定義の選び方で結果がどれだけ動くか。instructions とツールの説明文に入る
# (全期間 strict 355,708件 → broad 639,132件)
SEIKATSU_IMPACT = "broad は strict の約1.8倍の件数になる"

# strict / broad は引数の値。会話でそのまま書くと、初めて使う人には意味が分からない
SEIKATSU_WORDING = ("利用者への説明では strict / broad という語を使わず、"
                    "「" + "」「".join(d.label for d in SEIKATSU.values()) + "」のように"
                    "含める道路をそのまま書くこと")


def seikatsu_label(name: str) -> str:
    return SEIKATSU[name].label


def seikatsu_note(name: str) -> str:
    """集計結果に付ける注記。どの定義で数えたかを黙って済ませないため、必ず付ける。

    使った定義だけでなく全部の定義を並べる。片方しか書かないと、
    もう一方が何を指すのか、なぜ選べるのかが初めての人に伝わらない。
    """
    all_defs = "／".join(f"「{d.label}」" for d in SEIKATSU.values())
    return (f"{SEIKATSU_INTRO}（{all_defs}）。"
            f"この集計は「{seikatsu_label(name)}」で数えた。{SEIKATSU[name].impact}")


def seikatsu_choices() -> list[dict[str, str]]:
    """ビューの切り替えボタン。ボタンを HTML に書くと、定義を足したときに直し忘れる。"""
    return [{"value": k, "label": d.label, "title": d.includes} for k, d in SEIKATSU.items()]


def seikatsu_summary() -> str:
    """instructions と説明文に入れる一覧。Claude 向けなので引数の値も書く。
    例: strict（5.5m未満の道と、…）: …／broad（…）: …"""
    return "／".join(f"{k}（{d.label}）: {d.includes}" for k, d in SEIKATSU.items())


def seikatsu_codes_summary() -> str:
    """list_values の注記。例: 01,02,11(strict) または 01,02,11,14,17(broad)"""
    return " または ".join(f"{','.join(d.road_width)}({k})" for k, d in SEIKATSU.items())


# ── 年の数え方 ───────────────────────────────────────────────────────────
# year_basis の値と、使う人に見せる名前。「資料年次」は元データの列名で、
# そのまま見せても何の年か分からない

YEAR_BASIS_LABEL = {"資料年次": "統計に計上された年", "発生年": "事故が起きた年"}
YEAR_BASIS_DIFF = "年末に起きた事故の一部は翌年の統計に計上される"
YEAR_BASIS_WORDING = ("利用者への説明では「資料年次」「発生年」という語を使わず、"
                      "「" + "」「".join(YEAR_BASIS_LABEL.values()) + "」と書くこと")


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
        print(f"{name}: {d.label}　{d.includes}")
        for c in d.road_width:
            print(f"  {c} {' / '.join(vocab.ROAD_WIDTH[c])}")
    print("若年の歩行者・自転車:")
    for c in YOUNG_AGE:
        print(f"  年齢 {c} {' / '.join(vocab.AGE[c])}")
    for c in WALK_BIKE:
        print(f"  種別 {c} {' / '.join(vocab.PARTY_TYPE[c])}")
