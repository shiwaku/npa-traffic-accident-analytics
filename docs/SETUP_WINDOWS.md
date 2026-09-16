# Claude Desktop から使う（Windows / 経路A）

**経路A** は Claude Desktop がこのPCの `server.py` を stdio で起動して使う経路。
claude.ai から使う**経路B**は [REMOTE_CONNECTOR_MANUAL.md](REMOTE_CONNECTOR_MANUAL.md)。

経路Aには**トンネルも組織の Owner 権限も要らない**。サーバーの起動と終了は Desktop が
面倒を見るので、**手でサーバーを立てる操作は一切ない**。これが経路Bとのいちばん大きな違いで、
逆に「起動しておく」ことができないため、**設定を変えたら Desktop ごと再起動する**のが作法になる。

置くのはコードだけで、データ（96.6MB の Parquet）は R2 にある。集計のたびに必要な列だけを
HTTP Range で読む。ビューの `dist/*.html` はコミット済みなので **Node も npm も要らない**。

---

## このPCの現状（2026-09-16 実測）

| 項目 | 値 |
|---|---|
| Claude Desktop | `2.110.0.0`（Microsoft Store / MSIX 版） |
| 設定ファイル | `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json` |
| 登録名 | `npa-traffic-accident` |
| Python | `3.12.4` / `C:\Users\yshiw\AppData\Local\Programs\Python\Python312\python.exe` |
| 依存 | `duckdb 1.1.3` / `mcp` 導入済み（venv ではなくこの Python に直接） |
| リポジトリ | `C:\Users\yshiw\Documents\GIS\npa\npa-traffic-accident-analytics` |
| 接続 | 確認済み（`Server started and connected successfully`） |

**既に動いているので、下の 1〜3 は入れ直すとき・別のWindows機に入れるときだけ。**
日常的に使うのは「4. 接続を確認する」以降。

---

## 手順

### 1. コードを置く

リポジトリは public なので認証は要らない。

```powershell
git clone https://github.com/shiwaku/npa-traffic-accident-analytics.git C:\Users\<ユーザー名>\npa-traffic-accident-analytics
cd C:\Users\<ユーザー名>\npa-traffic-accident-analytics
python -m pip install -r mcp_server\requirements.txt
```

**Python は 3.10 以上**（`X | None` 記法と mcp パッケージの要件）。
`python --version` で確認する。

Windows の Python は `C:\Users\<ユーザー名>\AppData\Local\Programs\Python\` 配下に入る
ユーザーインストールなので、Mac と違って `externally-managed-environment` で弾かれない。
このPCも venv を作らず、その Python に直接入れている。venv を使う場合は
`.venv\Scripts\python.exe` を次のステップで指す。

### 2. 設定ファイルに登録する

**Microsoft Store（MSIX）版は `%APPDATA%\Claude` に設定ファイルが無い。**
パッケージ内にリダイレクトされている。このPCで `%APPDATA%\Claude` は存在しない。

| 入れ方 | 設定ファイルの場所 |
|---|---|
| Microsoft Store（MSIX）版 ← **このPC** | `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json` |
| インストーラ（exe）版 | `%APPDATA%\Claude\claude_desktop_config.json` |

どちらか分からなければ、両方 `Test-Path` で見て**存在するほう**が使われている。

```powershell
Test-Path "$env:APPDATA\Claude\claude_desktop_config.json"
Test-Path "$env:LOCALAPPDATA\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json"
```

エクスプローラで開くならこれが速い。

```powershell
explorer "$env:LOCALAPPDATA\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude"
```

中身はこう書く。ファイルが無ければ新規作成でよい。

```json
{
  "mcpServers": {
    "npa-traffic-accident": {
      "command": "C:\Users\<ユーザー名>\AppData\Local\Programs\Python\Python312\python.exe",
      "args": ["C:\Users\<ユーザー名>\npa-traffic-accident-analytics\mcp_server\server.py"]
    }
  }
}
```

つまずきやすいのはこの4点。

- **JSON なのでバックスラッシュは `\` と二重に書く。** `C:\Users` と書くと `\U` が
  不正なエスケープになって設定ファイル全体が読めなくなり、**サーバーが1つも出なくなる**
- **絶対パスのみ。** `~` も `%USERPROFILE%` も展開されない
- **`python.exe` を絶対パスで指す。** `"command": "python"` でも PATH が通っていれば動くが、
  別の Python を前に入れた瞬間に依存の入っていない側を掴んで壊れる
- 既に他のサーバーがあるなら `mcpServers` の中に1項目足すだけ。**直前の項目の末尾にカンマが要る**

保存したら JSON が壊れていないか確かめておく。

```powershell
Get-Content "$env:LOCALAPPDATA\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json" -Raw | ConvertFrom-Json | Out-Null; if ($?) { "JSON OK" }
```

### 3. Claude Desktop を再起動する

**設定は起動時にしか読まれない。** そして注意点が1つある。

**ウィンドウの × では終了しない。** タスクトレイに常駐するだけなので、そのまま起動し直しても
設定は読み直されない。**タスクトレイのアイコンを右クリック →「終了」**で本当に終わらせる。

```powershell
# 起動（MSIX 版はパスを直接叩けないのでアプリID指定）
Start-Process "shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude"
```

### 4. 接続を確認する

`設定 → 開発者 → ローカルMCPサーバー` に `npa-traffic-accident` が出ていれば繋がっている。

GUI を見なくても、**ログのほうが確実**。サーバーの stderr もここに出る。

```powershell
Get-Content "$env:LOCALAPPDATA\Claude\Logs\mcp-server-npa-traffic-accident.log" -Tail 20
```

**成功の目印**はこの3行。

```
[info] Using MCP server command: C:\Users\...\python.exe with path: {
[info] Server started and connected successfully
[info] Message from server: id=0 result
```

`Server disconnected` や `Server transport closed unexpectedly` が出ていたら、
`server.py` が起動に失敗して即死している。下の「つまずいたとき」へ。

起動中かどうかは、Desktop が生やした子プロセスを見ても分かる。

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select-Object ProcessId, CommandLine
```

### 5. 動作を確認する

[VERIFY_PROMPTS.md](VERIFY_PROMPTS.md) のプロンプトを**新しい会話**で上から貼る。
最初の2つだけ再掲する。

```
生活道路の事故件数を年別に出して。厳密定義で。
```

→ `seikatsu_dashboard`（strict）。2019年 65,188 件 … 2024年 45,296 件。
グラフ付きのビューが出れば描画 OK。

```
新宿駅から半径1kmの2024年の生活道路の事故を地図に出して。中心は 35.6896, 139.7006。
```

→ `accident_map`。**該当 82 件・描画 82 件**。背景の地理院ベクトルタイル（淡色）まで
出れば `_meta.ui.csp` の外部ドメイン宣言も効いている。

4〜8 はガードレールの確認で、**それらしい数字が返ってきたら不合格**という読み方をする。

---

## 更新する

```powershell
cd C:\Users\yshiw\Documents\GIS\npa\npa-traffic-accident-analytics
git pull
```

ビューの `dist\*.html` もリポジトリに入っているので `git pull` だけで最新になる。

**反映には Claude Desktop の再起動が要る。** そして
**子プロセスの `python.exe` を手で `taskkill` しない。** Desktop 側が繋ぎ直せずに固まることがある。
必ずトレイから「終了」→ 起動の順にする。

---

## server.py 側を切り分ける

Desktop が繋がらないとき、原因が「設定ファイル」なのか「`server.py` 自体」なのかを分ける。
**stdio は Desktop が握るので手で起動して確かめるのは難しい**が、代わりにこの2つで足りる。

```powershell
# 依存が入っているか
& "C:\Users\yshiw\AppData\Local\Programs\Python\Python312\python.exe" -c "import duckdb, mcp; print('deps OK')"

# server.py 自体が起動できるか（HTTP モードを借りる。確認できたら Ctrl+C）
cd C:\Users\yshiw\Documents\GIS\npa\npa-traffic-accident-analytics
python mcp_server\server.py --http --port 8000
```

`MCP endpoint: http://127.0.0.1:8000/mcp` が出れば、**import も R2 への接続も含めて
`server.py` は健全**。それでも Desktop から見えないなら原因は設定ファイル側にある。

この HTTP モードは経路Bで使うものだが、**経路Aと同時に動かしても問題ない**
（別プロセスで、データは読み取り専用）。

---

## つまずいたとき

| 症状 | 原因 | 対処 |
|---|---|---|
| `設定 → 開発者` にサーバーが1つも出ない | JSON が壊れている（`\` の書き忘れが多い） | 上の `ConvertFrom-Json` で検証。直したら Desktop を再起動 |
| このサーバーだけ出ない | 設定ファイルの場所が違う（MSIX 版なのに `%APPDATA%\Claude` に書いた） | 「2. 設定ファイルに登録する」の表で場所を確認 |
| ログに `Server disconnected` | `command` の Python が存在しない／依存が入っていない | 「server.py 側を切り分ける」の2コマンドを実行 |
| ログに `ModuleNotFoundError` | 依存を別の Python に入れた | `command` が指す Python で `pip install -r mcp_server\requirements.txt` |
| 設定を直したのに変わらない | × で閉じただけで終了していない | タスクトレイ右クリック →「終了」→ 起動 |
| `git pull` したのに古い挙動のまま | 同上。Desktop の再起動が要る | 同上 |
| ツールは見えるがビューが出ず数字だけ | ホストが MCP Apps をネゴシエートしていない | Claude Desktop なら描画される。ターミナルの Claude Code は数字だけ（集計としては正常） |
| 地図は出るが背景が白い | `_meta.ui.csp` の外部ドメイン宣言が効いていない | サーバー側の CSP 宣言を確認 |
| 集計が返ってこない | R2 へ出られていない（オフライン・プロキシ） | 「server.py 側を切り分ける」の HTTP モードで起動を確認 |

---

## 経路Bとの関係

**同時に動かしてよい。** 別プロセスで互いを知らず、データは R2 上の読み取り専用 Parquet なので
競合しない。経路Bのトンネルとサーバーを落としても、経路Aは動き続ける。

ただし **Claude Desktop 側で経路Bのリモートコネクタを有効にしない**。
開発者タブの stdio と同じツールが2組並んで紛らわしくなる。

`mcpServers` は**アカウント単位ではなくPC単位**なので、会社アカウントに切り替えても
同じサーバーが見える。**組織の Owner 権限は要らない**（同じファイル内の他の設定が
`...ByAccount` でアカウントごとに分かれているのに対し、`mcpServers` は分かれていない）。

---

## 関連

- Mac に入れる手順は [SETUP_MAC.md](SETUP_MAC.md)
- 経路B（claude.ai）の逐次手順は [REMOTE_CONNECTOR_MANUAL.md](REMOTE_CONNECTOR_MANUAL.md)、
  仕組みと構成図は [REMOTE_CONNECTOR.md](REMOTE_CONNECTOR.md)
- 動作確認プロンプトの全文と期待値は [VERIFY_PROMPTS.md](VERIFY_PROMPTS.md)
- 質問1つで何が起きるかは [HOW_IT_WORKS.md](HOW_IT_WORKS.md)
