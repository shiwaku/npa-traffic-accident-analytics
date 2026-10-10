"""公開した MCP エンドポイントを叩いて、応答時間と中身を確かめる。

    python probe.py list  http://localhost:8787/mcp          # ツール一覧と入力スキーマ
    python probe.py run   http://localhost:8787/mcp          # 代表的な呼び出しを順に打って時間を出す
    python probe.py cold  http://localhost:8787/mcp          # 最初の initialize が通るまでの秒数
    python probe.py load  http://localhost:8787/mcp 40       # 40 セッションを同時に流して応答時間の分布を出す

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


# 発表会で来場者が触る流れ。県と地図の中心を人ごとに変え、同じ問い合わせが重ならないようにする。
LOAD_PREFS = ["東京都", "大阪", "愛知県", "神奈川県", "千葉県", "埼玉県", "福岡県", "北海道"]


def _load_calls(i: int) -> list[tuple[str, dict]]:
    pref = LOAD_PREFS[i % len(LOAD_PREFS)]
    return [
        ("seikatsu_dashboard", {}),
        ("aggregate", {"group_by": ["year"], "prefecture": [pref]}),
        ("accident_map", {"prefecture": [pref], "max_points": 5000}),
        ("accident_map", {"center_lat": 35.6896 + 0.01 * (i % 10), "center_lon": 139.7006,
                          "radius_m": 1000}),
    ]


async def _load_one(url: str, i: int, ramp_s: float, out: list) -> None:
    await asyncio.sleep(ramp_s * i)
    t0 = time.perf_counter()
    try:
        async with _session(url) as s:
            out.append(("initialize", time.perf_counter() - t0, None))
            for name, args in _load_calls(i):
                t = time.perf_counter()
                try:
                    r = await s.call_tool(name, args)
                    err = (r.content[0].text if r.content else "error")[:120] if r.is_error else None
                except Exception as e:  # noqa: BLE001  落ちた呼び出しも数える
                    err = f"{type(e).__name__}: {e}"[:120]
                out.append((name, time.perf_counter() - t, err))
    except BaseException as e:  # noqa: BLE001  接続ごと落ちた
        out.append(("session", time.perf_counter() - t0, f"{type(e).__name__}: {e}"[:120]))


async def cmd_load(url: str, n: int = 40, ramp_s: float = 0.25) -> None:
    """n セッションを ramp_s 秒おきに立ち上げ、各セッションで _load_calls を順に呼ぶ。"""
    out: list[tuple[str, float, str | None]] = []
    t0 = time.perf_counter()
    await asyncio.gather(*(_load_one(url, i, ramp_s, out) for i in range(n)))
    print(f"{n} sessions, ramp {ramp_s}s, total {time.perf_counter() - t0:.1f}s")
    print(f"{'call':<20}{'n':>4}{'err':>5}{'p50':>8}{'p95':>8}{'max':>8}")
    for name in dict.fromkeys(k for k, _, _ in out):
        ts = sorted(t for k, t, _ in out if k == name)
        errs = [e for k, _, e in out if k == name and e]
        p = lambda q: ts[min(len(ts) - 1, int(q * len(ts)))]  # noqa: E731
        print(f"{name:<20}{len(ts):>4}{len(errs):>5}{p(.5):>7.2f}s{p(.95):>7.2f}s{ts[-1]:>7.2f}s")
    for e in dict.fromkeys(e for _, _, e in out if e):
        print("  ERROR:", e)


if __name__ == "__main__":
    cmd, url = sys.argv[1], sys.argv[2]
    if cmd == "load":
        asyncio.run(cmd_load(url, *(int(sys.argv[3]),) if len(sys.argv) > 3 else ()))
    else:
        asyncio.run({"list": cmd_list, "run": cmd_run, "cold": cmd_cold}[cmd](url))
