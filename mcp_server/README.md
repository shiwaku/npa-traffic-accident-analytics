# MCPサーバー

R2 上の GeoParquet を DuckDB で集計する MCP サーバー。
利用者は自分の Claude から日本語で聞くだけでよく、SQL も定義の知識も要らない。

## ツール

| | |
|---|---|
| `aggregate` | 条件を指定して集計する。主にこれを使う |
| `list_values` | 項目の有効なコード値とラベルと件数を返す |
| `run_sql` | `aggregate` で表現できない集計のための逃げ道。読み取り専用 |

## 設計の要点

**引数はラベル文字列ではなくコード値で受け取る。** コード表のラベルは全角ハイフン
マイナス(U+FF0D)と全角チルダ(U+FF5E)を含み、似た別文字を1つ混ぜるとクエリは
エラーにならず0件を返す。`'01','02','11'` のようなASCIIのコードで受けて
サーバー側でラベルに変換すれば、この事故が構造的に起きない。

**1コードが複数ラベルを持つ場合がある。** 当事者種別の `36` は2023年以前が
`二輪車－原付自転車`、2024年以降が `二輪車－一般原付自転車`。`vocab.py` は
2019〜2024の全年次を統合しているので、年次をまたいでも取りこぼさない。

**`run_sql` は文字列リテラルを自動修復する。** 似た別文字が混ざっていた場合は
正しいラベルに直し、直した内容を `corrections` として返す。黙って直さない。

**返り値に実行したSQLを含める。** 数字の出どころを確認できるようにするため。

`vocab.py` は `converter/codes` から機械生成したもの。手で編集しないこと。

## 動かす

```bash
pip install -r mcp_server/requirements.txt

python mcp_server/server.py                     # stdio
python mcp_server/server.py --http --port 8000  # HTTP（リモートコネクタ用）
```

Claude Code への登録:

```bash
claude mcp add npa-traffic-accident --scope user -- python <このファイルの絶対パス>/server.py
```

claude.ai のカスタムコネクタとして使うには、`--http` で起動したものを
公開HTTPSで到達できる場所に置く必要がある。設置先は未定（docs/DESIGN.md 参照）。

## 定義

指標・ディメンションの定義は [../CLAUDE.md](../CLAUDE.md) が正典。
ツールの説明文とサーバーの instructions はそこから移植している。
