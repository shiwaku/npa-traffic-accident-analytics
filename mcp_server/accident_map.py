# -*- coding: utf-8 -*-
"""事故地点マップのビュー(MCP Apps の ui:// リソース)。

`app/` を Vite でビルドした単一HTMLを配る点は dashboard.py と同じ。
違うのは、このビューが MapLibre GL で外部のベクトルタイルを読むこと。

    cd mcp_server/app && npm install && npm run build

**Artifact と違い、MCP Apps のビューは外部ドメインを宣言できる。**
宣言しない限りサンドボックスiframeは一切の通信を拒否するため、地理院タイルと
グリフ(フォント)・スプライトのドメインを CSP に載せる必要がある。
参照ホスト実装の CSP は `worker-src 'self' blob:` を含むので、MapLibre の
Web Worker は動く(宣言不要)。
"""
from __future__ import annotations

import pathlib

from mcp.server.apps import ResourceCsp

RESOURCE_URI = "ui://npa-traffic-accident/accident-map.html"

# ベクトルタイル本体と、グリフ・スプライト。fetch で取りに行くので connect にも要る。
_GSI_DOMAINS = [
    "https://cyberjapandata.gsi.go.jp",   # 最適化ベクトルタイル(.pbf)
    "https://gsi-cyberjapan.github.io",   # glyphs / sprite
]

CSP = ResourceCsp(connectDomains=_GSI_DOMAINS, resourceDomains=_GSI_DOMAINS)

_BUILT = pathlib.Path(__file__).with_name("app") / "dist" / "map-app.html"


def load_html() -> str:
    """ビルド済みのビューを読む。未ビルドなら何が足りないかを言って落ちる。"""
    if not _BUILT.exists():
        raise FileNotFoundError(
            f"ビューが未ビルド: {_BUILT}\n"
            "  cd mcp_server/app && npm install && npm run build"
        )
    return _BUILT.read_text(encoding="utf-8")
