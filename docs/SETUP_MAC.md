# 別のマシンに入れる（Mac / Claude Desktop）

会社アカウントの Claude で使いたい場合、**現実的な経路は Claude Desktop の
ローカルMCPサーバー（stdio）だけ**。理由は [なぜ stdio なのか](#なぜ-stdio-なのか) に書いた。

**Windows は [SETUP_WINDOWS.md](SETUP_WINDOWS.md)。** 設定ファイルの場所と再起動の作法が違う。

置くのは**コードだけ**で、データ（96.6MB の Parquet）は R2 にあるので落ちてこない。
集計のたびに必要な列だけを HTTP Range で読む。ビューの `dist/*.html` はコミット済みなので
**Node も npm も要らない**。

---

## 手順

### 1. コードを置く

リポジトリは public なので認証は要らない。

```bash
git clone https://github.com/shiwaku/npa-traffic-accident-analytics.git ~/npa-traffic-accident-analytics
cd ~/npa-traffic-accident-analytics
python3 -m venv .venv && .venv/bin/pip install -r mcp_server/requirements.txt
```

**Python は 3.10 以上**（`X | None` 記法と mcp パッケージの要件）。
macOS 標準の `python3` が古い場合は `brew install python@3.12` などで入れる。

venv を作るのは、会社支給機の system Python を汚さないためと、
`pip install` が `externally-managed-environment` で弾かれるのを避けるため。

### 2. 設定ファイルに登録する

`~/Library/Application Support/Claude/claude_desktop_config.json` を開く
（Mac 版は通常の場所にある。Windows の MSIX 版はパッケージ内にリダイレクトされていて別）。
無ければ新規作成でよい。

```json
{
  "mcpServers": {
    "npa-traffic-accident": {
      "command": "/Users/<ユーザー名>/npa-traffic-accident-analytics/.venv/bin/python",
      "args": ["/Users/<ユーザー名>/npa-traffic-accident-analytics/mcp_server/server.py"]
    }
  }
}
```

つまずきやすいのはこの3点。

- **絶対パスのみ。`~` は展開されない**
- **venv の python を直接指す。** `python3` と書くと依存が入っていない側を掴む
- 既に他のサーバーがあるなら `mcpServers` の中に1項目足すだけ。**直前の項目の末尾にカンマが要る**

`<ユーザー名>` は `whoami` の出力に置き換える。

### 3. Claude Desktop を再起動する

設定は起動時に読まれる。再起動したら
`設定 → 開発者 → ローカルMCPサーバー` に `npa-traffic-accident` が出る。

### 4. 動作を確認する

[VERIFY_PROMPTS.md](VERIFY_PROMPTS.md) のプロンプトを上から貼る。
1〜3 でビュー（表・地図・集計表）が描画されれば成功。

動かないときは `~/Library/Logs/Claude/mcp-server-npa-traffic-accident.log` を見る。
サーバーの stderr がそこに出る。

---

## なぜ stdio なのか

| 使いたい場所 | 可否 | 条件 |
|---|---|---|
| 会社Macの Claude Desktop | **できる** | このページの手順。Owner 権限もトンネルも不要 |
| 会社の claude.ai | **今は無理** | Owner にコネクタを追加してもらう + 常時稼働するサーバー |
| 個人の claude.ai | できる | [REMOTE_CONNECTOR.md](REMOTE_CONNECTOR.md)。URLは起動のたびに変わる |

**`claude_desktop_config.json` の `mcpServers` はアカウント単位ではなくPC単位。**
同じファイル内の他の設定が `...ByAccount` でアカウントごとに分かれているのに対し、
`mcpServers` は分かれていない。だから会社アカウントに切り替えても同じサーバーが見え、
**組織の Owner 権限は要らない**。

一方 **claude.ai はブラウザなのでローカルのプロセスを起動できない**。URLを登録する
リモートコネクタ一択になり、Team/Enterprise ではカスタムコネクタを追加できるのは
**組織の Owner だけ**。加えてサーバーがどこかで動き続けている必要がある（issue #3）。

---

## 更新する

```bash
cd ~/npa-traffic-accident-analytics && git pull
```

`dist/*.html`（ビュー）もリポジトリに入っているので、`git pull` だけで最新になる。
**反映には Claude Desktop の再起動が要る**（子プロセスを落としても張り直さない）。
