"""コンテナの起動処理。parquet をローカルディスクに落としてからサーバーを起動する。

httpfs で R2 を直接読むと、1クエリが数十〜数百の Range リクエストになり、
1 vCPU でもダッシュボード集計に 25 秒かかった(コンテナからの実測)。
同じ parquet をローカルディスクから読むと 0.5 秒。96 MB を起動時に 1 回落とす方が
ずっと安い。コンテナが寝て起きるたびに落とし直す(ディスクは残らない)。
"""
from __future__ import annotations

import os
import sys
import time
import urllib.request

URL = os.environ.get(
    "NPA_PARQUET_URL",
    "https://shi-works.com/geoparquet/npa-traffic-accident-analytics/honhyo_2019-2024.parquet",
)
LOCAL = "/data/honhyo.parquet"


def main() -> None:
    if URL.startswith("http"):
        t = time.perf_counter()
        os.makedirs(os.path.dirname(LOCAL), exist_ok=True)
        # shi-works.com は Cloudflare の bot 対策で "Python-urllib/*" を 403 にする。名乗りを変える
        req = urllib.request.Request(URL, headers={"User-Agent": "npa-traffic-accident-mcp/1.0"})
        with urllib.request.urlopen(req) as r, open(LOCAL, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        mb = os.path.getsize(LOCAL) / 1e6
        print(f"parquet: {mb:.1f} MB downloaded in {time.perf_counter() - t:.1f}s", file=sys.stderr)
        os.environ["NPA_PARQUET_URL"] = LOCAL
    os.execvp(sys.executable, [sys.executable, "mcp_server/server.py", *sys.argv[1:]])


if __name__ == "__main__":
    main()
