# -*- coding: utf-8 -*-
"""生活道路ダッシュボードのビュー(MCP Apps の ui:// リソース)。

HTML は手書きではなく `app/` を Vite でビルドしたもの。ビュー本体は
MCP Apps SDK (`@modelcontextprotocol/ext-apps`) の `App` クラスを使い、
ui/initialize のハンドシェイク・tool-result の受信・tools/call の送出・
サイズ通知はすべて SDK 側の実装に任せている。

    cd mcp_server/app && npm install && npm run build

vite-plugin-singlefile が JS と CSS を1枚の HTML に畳み込む。サンドボックス
iframe は外部アセットを取りに行けないため、これは必須。
"""
from __future__ import annotations

import pathlib

RESOURCE_URI = "ui://npa-traffic-accident/seikatsu-dashboard.html"

_BUILT = pathlib.Path(__file__).with_name("app") / "dist" / "mcp-app.html"


def load_html() -> str:
    """ビルド済みのビューを読む。未ビルドなら何が足りないかを言って落ちる。"""
    if not _BUILT.exists():
        raise FileNotFoundError(
            f"ビューが未ビルド: {_BUILT}\n"
            "  cd mcp_server/app && npm install && npm run build"
        )
    return _BUILT.read_text(encoding="utf-8")
