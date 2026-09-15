# -*- coding: utf-8 -*-
"""集計表のビュー(MCP Apps の ui:// リソース)。

`aggregate` の結果をそのまま描く。dashboard.py と同じく単一HTMLを配るだけで、
外部リソースは一切読まない(表なのでタイルもフォントも要らない)。

    cd mcp_server/app && npm install && npm run build

このビューが担うのは3つ。

  1. 件数だけでなく構成比を併記する。年を含む集計では指数(基準年=100)も出す
  2. group_by が2つのときは行列に畳んで塗り分ける。年×都道府県のような
     組み合わせは、平らな表のままだと読めない
  3. 列見出しで並べ替える

再集計はしない。絞り込みを変えるのは会話側の仕事で、ビューは受け取った
結果を読ませることに徹する。
"""
from __future__ import annotations

import pathlib

RESOURCE_URI = "ui://npa-traffic-accident/aggregate-table.html"

_BUILT = pathlib.Path(__file__).with_name("app") / "dist" / "table-app.html"


def load_html() -> str:
    """ビルド済みのビューを読む。未ビルドなら何が足りないかを言って落ちる。"""
    if not _BUILT.exists():
        raise FileNotFoundError(
            f"ビューが未ビルド: {_BUILT}\n"
            "  cd mcp_server/app && npm install && npm run build"
        )
    return _BUILT.read_text(encoding="utf-8")
