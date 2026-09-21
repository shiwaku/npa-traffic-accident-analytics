# MCP サーバーを Cloudflare Containers で動かすためのイメージ。
# ビルドコンテキストはリポジトリ直下(wrangler.jsonc の image_build_context)。
# Containers は linux/amd64 のみ(wrangler が --platform を付けてビルドする)。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY mcp_server/requirements.txt mcp_server/requirements.txt
RUN pip install -r mcp_server/requirements.txt

# httpfs 拡張はサーバー起動時に INSTALL される。コールドスタートのたびに
# 拡張を取りに行かないよう、ビルド時に入れて ~/.duckdb に焼いておく。
RUN python -c "import duckdb; duckdb.connect().execute('INSTALL httpfs')"

COPY mcp_server/ mcp_server/
COPY deploy/cloudflare/entrypoint.py entrypoint.py

EXPOSE 8080

# entrypoint.py が parquet をローカルに落としてから server.py を exec する。
# Host ヘッダは Worker 経由の公開ホスト名で届き、コンテナには Worker 以外から
# 到達できないので、DNS リバインディング検証は '*' で外す。
CMD ["python", "entrypoint.py", "--http", "--host", "0.0.0.0", "--port", "8080", "--allow-host", "*"]
