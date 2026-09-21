"""公開した MCP エンドポイントを叩いて、応答時間と中身を確かめる。

    python probe.py list  http://localhost:8787/mcp          # ツール一覧と入力スキーマ
    python probe.py run   http://localhost:8787/mcp          # 代表的な呼び出しを順に打って時間を出す
    python probe.py cold  http://localhost:8787/mcp          # 最初の initialize が通るまでの秒数

Worker の秘密パスを使っているときは URL に /s/<SECRET_PATH>/mcp を渡す。
依存は mcp (>=2.2.0) だけ。mcp_server/requirements.txt を入れていれば動く。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

# 実運用で重い側の呼び出し。全年・全国の集計と、地図の上限いっぱい。
CALLS: list[tuple[str, dict]] = [
    ("seikatsu_dashboard", {}),
    ("aggregate", {"group_by": ["year"]}),
    ("accident_map", {"prefecture": ["東京都"], "max_points": 20000}),
]


@contextlib.asynccontextmanager
async def _session(url: str):
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            yield s


async def cmd_list(url: str) -> None:
    async with _session(url) as s:
        tools = await s.list_tools()
        for t in tools.tools:
            props = t.input_schema.get("properties", {})
            print(f"{t.name}: {', '.join(props)}")
        res = await s.list_resources()
        for r in res.resources:
            print(f"resource {r.uri}")


async def cmd_run(url: str) -> None:
    t0 = time.perf_counter()
    async with _session(url) as s:
        print(f"initialize        {time.perf_counter() - t0:6.2f}s")
        t = time.perf_counter()
        tools = await s.list_tools()
        print(f"tools/list        {time.perf_counter() - t:6.2f}s  ({len(tools.tools)} tools)")
        for name, args in CALLS:
            t = time.perf_counter()
            r = await s.call_tool(name, args)
            size = len(json.dumps(r.structured_content or {}, ensure_ascii=False))
            print(f"{name:<18}{time.perf_counter() - t:6.2f}s  structured {size:,} B")
            if getattr(r, "is_error", False):
                print("   ERROR:", (r.content[0].text if r.content else "")[:300])
        for uri in [r.uri for r in (await s.list_resources()).resources]:
            t = time.perf_counter()
            try:
                r = await s.read_resource(uri)
            except Exception as e:  # noqa: BLE001  1件落ちても残りは読む
                print(f"{str(uri):<40}{time.perf_counter() - t:6.2f}s  ERROR {e}")
                continue
            body = r.contents[0]
            n = len(getattr(body, "text", "") or getattr(body, "blob", ""))
            print(f"{str(uri):<40}{time.perf_counter() - t:6.2f}s  {n:,} B")


async def cmd_cold(url: str) -> None:
    t0 = time.perf_counter()
    while True:
        try:
            async with _session(url):
                print(f"first initialize ok after {time.perf_counter() - t0:.1f}s")
                return
        except BaseException:  # noqa: BLE001  接続拒否・502 など、起動中は何でも来る
            if time.perf_counter() - t0 > 180:
                raise
            await asyncio.sleep(0.5)


if __name__ == "__main__":
    cmd, url = sys.argv[1], sys.argv[2]
    asyncio.run({"list": cmd_list, "run": cmd_run, "cold": cmd_cold}[cmd](url))
