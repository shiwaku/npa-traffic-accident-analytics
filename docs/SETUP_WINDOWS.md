# Claude Desktop から使う（Windows）

**何も準備していない Windows PC** で、Claude Desktop からこのリポジトリの交通事故データ
（2019〜2024年・1,895,275件）を集計できるようになるまでの手順。

上から順に実行すれば終わる。**所要 15分ほど**（Python が既に入っていれば5分）。

## これができるようになる

Claude Desktop にこう聞くと、グラフ付きで答えが返る。

```
生活道路の事故件数を年別に出して。厳密定義で。
```

- **データはダウンロードされない。** 96.6MB の Parquet はクラウド（Cloudflare R2）にあり、
  集計のたびに必要な列だけを読む。PCに置くのはコードだけ
- **組織の Owner 権限もトンネルも要らない。** Claude Desktop が PC の中だけで完結して動かす
- ブラウザの claude.ai から使いたい場合は**この手順では足りない**。
  [REMOTE_CONNECTOR_MANUAL.md](REMOTE_CONNECTOR_MANUAL.md) を見る

## 必要なもの

| | 必要 | どこで使うか |
|---|---|---|
| Claude Desktop | **必須** | 全体 |
| Python 3.10 以上 | **必須** | 手順1。無ければ入れる |
| Git | あると楽 | 手順2。無くても ZIP で代用できる |
| インターネット接続 | **必須** | 集計のたびに使う |

**Node.js と npm は要らない。** 画面表示に使う `dist\*.html` はリポジトリに入っている。

---

## 準備. PowerShell を開く

以降のコマンドはすべて PowerShell に貼り付ける。

`Windows キー + X` → **「ターミナル」**（または「Windows PowerShell」）を選ぶ。
管理者権限は要らない。

---

## 1. Python を確認する

```powershell
python --version
```

**`Python 3.10.x` 以上が出れば OK。** 次へ進む。

`Python was not found` と出る、または Microsoft Store が開いた場合は入っていない。
[python.org](https://www.python.org/downloads/windows/) から入れる。インストーラ最初の画面の
**「Add python.exe to PATH」に必ずチェックを入れる**。入れ終えたら
**PowerShell を開き直してから** もう一度 `python --version` を実行する。

### どの python が使われるか見ておく

あとで設定ファイルに**絶対パスで**書く。パスは手順5でコマンドが自動で拾うので
メモは要らないが、1つだけ罠があるので確認しておく。

```powershell
(Get-Command python).Source
```

```
C:\Users\<ユーザー名>\AppData\Local\Programs\Python\Python312\python.exe
```

**`WindowsApps\python.exe` と出たら要注意。** それは Microsoft Store を開くだけの
ショートカットで、設定に書いても動かない。python.org 版を入れ直すか、
`設定 → アプリ → アプリ実行エイリアス` で「アプリ インストーラー python.exe」を
オフにしてから PowerShell を開き直す。

---

## 2. コードを置く

置き場所はどこでもよいが、この手順では `C:\Users\<ユーザー名>\npa-traffic-accident-analytics`
に置く。これを**「リポジトリのパス」**と呼ぶ。

**Git がある場合:**

```powershell
cd $env:USERPROFILE
git clone https://github.com/shiwaku/npa-traffic-accident-analytics.git
```

**Git が無い場合:** [リポジトリ](https://github.com/shiwaku/npa-traffic-accident-analytics)
の緑の `Code` ボタン → `Download ZIP` を押し、展開して上のパスに置く。展開すると
`npa-traffic-accident-analytics-main` という名前になるので、`-main` を外す。

リポジトリは public なので、どちらの方法でも GitHub のアカウントは要らない。

**別の場所に置いた場合**（例: `D:\work\` や `ドキュメント` の下）、以降に出てくる
`cd $env:USERPROFILE\npa-traffic-accident-analytics` は**そのパスに読み替える**。
手順5でここを間違えると動かないが、その場で気づけるようになっている。

---

## 3. 依存を入れる

```powershell
cd $env:USERPROFILE\npa-traffic-accident-analytics
python -m pip install -r mcp_server\requirements.txt
```

入るのは `duckdb`（集計エンジン）と `mcp`（Claude と話すための部品）の2つ。

確認する。

```powershell
python -c "import duckdb, mcp; print('OK')"
```

`OK` と出れば次へ。

> **venv（仮想環境）について**
> Windows の Python はユーザー配下に入るので、Mac のように
> `externally-managed-environment` で弾かれることはなく、venv 無しで問題ない。
> 使う場合は `python -m venv .venv` のあと
> `.venv\Scripts\python.exe -m pip install -r mcp_server\requirements.txt` とし、
> 手順5-2 の `$py = (Get-Command python).Source` を
> `$py = (Resolve-Path .\.venv\Scripts\python.exe).Path` に置き換える。

---

## 4. 設定ファイルの場所を調べる

Claude Desktop には**入れ方が2通りあり、設定ファイルの場所が違う**。Microsoft Store 版は
パッケージ内にリダイレクトされていて、よく紹介される `%APPDATA%\Claude` には**無い**。

どちらか判定して、使うパスを `$cfg` に入れる。そのまま貼る。

```powershell
$cfg = if (Get-AppxPackage -Name "*Claude*" -ErrorAction SilentlyContinue) { "$env:LOCALAPPDATA\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json" } else { "$env:APPDATA\Claude\claude_desktop_config.json" }
"設定ファイル: $cfg"
"存在するか: " + (Test-Path $cfg)
```

`存在するか: False` でも問題ない。手順5で作る。

> **`$cfg` は PowerShell を閉じると消える。**
> 以降のコマンドで
> `Get-Content : 引数が null であるため、パラメーター 'Path' にバインドできません`
> と出たら、**この1行目をもう一度貼る**だけでよい。ウィンドウを開き直したとき、
> PC を再起動したときに起きる。

フォルダをエクスプローラで開くならこれ。

```powershell
New-Item -ItemType Directory -Force (Split-Path $cfg) | Out-Null
explorer (Split-Path $cfg)
```

---

## 5. 設定ファイルを書く

### 5-1. 既にあるならバックアップする

他の MCP サーバーを使っている場合、この後の編集で壊すと**それも全部使えなくなる**。

```powershell
if (Test-Path $cfg) { Copy-Item $cfg "$env:TEMP\claude_desktop_config.backup.json"; "バックアップした" }
```

### 5-2. 貼る内容を作る

**パスを手で書き写さない。** ここで間違えるのが最も多い失敗なので、
実際のパスから貼れる形を生成する。**リポジトリのパスに移動してから**実行する。

```powershell
cd $env:USERPROFILE\npa-traffic-accident-analytics
$py  = (Get-Command python).Source
$srv = (Resolve-Path .\mcp_server\server.py).Path
if ($py -like "*WindowsApps*") { "!! python が Microsoft Store のショートカットです。手順1をやり直してください" }
'"npa-traffic-accident": {'
'  "command": "' + $py.Replace('\','\\') + '",'
'  "args": ["' + $srv.Replace('\','\\') + '"]'
'}'
```

**`cd` の行は自分がコードを置いた場所に直す。** 手順2で別の場所に置いたなら、その絶対パス。
場所が違えば `Resolve-Path` がエラーになるので、間違ったまま進むことはない。

4行が出力される。これが貼る内容。

```
"npa-traffic-accident": {
  "command": "C:\\Users\\<ユーザー名>\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
  "args": ["C:\\...\\npa-traffic-accident-analytics\\mcp_server\\server.py"]
}
```

バックスラッシュが `\\` と2つになっているのは**正しい**。JSON ではこれが必要で、
`C:\Users` のように1つで書くと `\U` が壊れた記号と解釈され、**設定ファイル全体が
読めなくなって MCP サーバーが1つも出なくなる**。上のコマンドはこの変換も済ませている。

### 5-3. ファイルに貼る

手順4で表示されたパスのファイルを開く。

```powershell
notepad $cfg
```

**ファイルが空、または新規作成の場合** — 全体をこうする（`...` が 5-2 の出力4行）。

```json
{
  "mcpServers": {
    ...
  }
}
```

**既に `mcpServers` がある場合** — その `{ }` の中に 5-2 の出力を足す。
**直前の項目の閉じ `}` の後ろにカンマが要る。**

```json
{
  "mcpServers": {
    "既にあるサーバー": { "command": "...", "args": ["..."] },
    ...
  },
  "他の設定": "触らない"
}
```

`mcpServers` 以外のキー（`preferences` など）があっても**消さない**。

### 5-4. 壊れていないか確かめる

保存したら、必ずこれを実行する。

```powershell
Get-Content $cfg -Raw | ConvertFrom-Json | Out-Null; if ($?) { "JSON OK" }
```

**`JSON OK` が出るまで先に進まない。** 出ない場合はエラーに位置が出るので、
その付近の `\\` とカンマを見直す。

`パラメーター 'Path' にバインドできません` と出た場合は JSON の問題ではなく、
**`$cfg` が消えている**（PowerShell を開き直した）。手順4の1行目を貼り直す。

`JSON OK` は**「JSON として壊れていない」だけ**で、登録できたことまでは意味しない。
中身も確かめておく。

```powershell
(Get-Content $cfg -Raw | ConvertFrom-Json).mcpServers | ConvertTo-Json -Depth 5
```

`npa-traffic-accident` と自分の書いたパスが出れば手順6へ。`{ }` と空なら貼れていない。

---

## 6. Claude Desktop を再起動する

**設定ファイルは起動したときにしか読まれない。** そして注意点が1つある。

**ウィンドウの × では終了しない。** タスクトレイ（画面右下）に居座るだけなので、
そのまま開き直しても設定は読み直されない。

1. タスクトレイの Claude アイコンを**右クリック →「終了」**
2. Claude Desktop を起動し直す

コマンドで終了・起動してもよい。

```powershell
Get-Process Claude -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*WindowsApps*" } | Stop-Process -Force
Start-Process "shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude"
```

（起動コマンドは Microsoft Store 版のもの。インストーラ版はスタートメニューから普通に開く）

---

## 7. 繋がったか確認する

### 画面で見る

`設定 → 開発者 → ローカルMCPサーバー` に **`npa-traffic-accident`** が出ていれば繋がっている。

### ログで見る（確実）

```powershell
Get-Content "$env:LOCALAPPDATA\Claude\Logs\mcp-server-npa-traffic-accident.log" -Tail 20
```

**この2行**があれば成功。

```
[info] Using MCP server command: C:\...\python.exe with path: {
[info] Server started and connected successfully
```

`Server disconnected` や `Server transport closed unexpectedly` が出ていたら、
`server.py` が起動できずに即終了している。下の「うまくいかないとき」へ。

---

## 8. 使ってみる

Claude Desktop で**新しい会話**を開いて貼る。

```
生活道路の事故件数を年別に出して。厳密定義で。
```

グラフ付きの表示で、2019年 **65,188件** … 2024年 **45,296件** と出れば完了。

```
新宿駅から半径1kmの2024年の生活道路の事故を地図に出して。中心は 35.6896, 139.7006。
```

地図が出て **82件** なら、地図表示も動いている。背景の地図タイルまで出れば完璧。

他の確認用プロンプトと期待値は [VERIFY_PROMPTS.md](VERIFY_PROMPTS.md) にある。

**使い始める前に [CLAUDE.md](../CLAUDE.md) を読むこと。** 「生活道路」の定義が2通りある、
年齢は実年齢ではなく年齢層である、といった**知らずに集計すると
エラーにならずに間違った数字が出る**前提がまとまっている。

---

## うまくいかないとき

| 症状 | 原因 | 対処 |
|---|---|---|
| `パラメーター 'Path' にバインドできません` | `$cfg` が消えた（PowerShell を開き直した） | 手順4の1行目を貼り直す |
| `設定 → 開発者` にサーバーが**1つも**出ない | JSON が壊れている（カンマ抜け・`\\` の書き忘れ） | 手順5-4 を実行。`JSON OK` が出るまで直す |
| このサーバー**だけ**出ない | 設定ファイルの場所が違う | 手順4をやり直す。Store 版なのに `%APPDATA%\Claude` に書いていないか |
| ログに `Server disconnected` | `command` の Python が存在しない | 手順5-2 を実行し直して出力をそのまま貼る。`WindowsApps\python.exe` になっていたら手順1へ |
| ログに `can't open file ... server.py` | `args` のパスが実際の置き場所と違う | **リポジトリのパスに `cd` してから**手順5-2 を実行し直す |
| ログに `ModuleNotFoundError` | 依存が別の Python に入った | `command` に書いたパスで `<そのパス> -m pip install -r mcp_server\requirements.txt` |
| ログファイルが無い | 一度も起動を試みていない | 手順6の再起動をやり直す |
| 設定を直したのに変わらない | × で閉じただけで終了していない | トレイ右クリック →「終了」→ 起動 |
| ツールは動くが**グラフや地図が出ず数字だけ** | 表示に対応していない画面で使っている | Claude Desktop なら出る。ターミナルの Claude Code では数字だけ（集計は正常） |
| 地図は出るが**背景が白い** | 地図タイルの取得が通っていない | ネットワーク（プロキシ等）を確認 |
| 集計が返ってこない | クラウドのデータに届いていない | 下の「サーバー単体で切り分ける」 |

### サーバー単体で切り分ける

原因が**設定ファイル**なのか **`server.py` 自体**なのかを分ける。

```powershell
cd $env:USERPROFILE\npa-traffic-accident-analytics
python mcp_server\server.py --http --port 8000
```

`MCP endpoint: http://127.0.0.1:8000/mcp` と出れば、**依存もクラウドへの接続も含めて
`server.py` は正常**。原因は設定ファイル側にある。確認できたら `Ctrl + C` で止める。

（これは本来 claude.ai 用のモードだが、起動確認に借りている。Claude Desktop と
同時に動かしても支障はない）

---

## 更新する

```powershell
cd $env:USERPROFILE\npa-traffic-accident-analytics
git pull
```

画面表示に使う `dist\*.html` もリポジトリに入っているので、`git pull` だけで最新になる。
ZIP で入れた場合は ZIP を取り直して置き換える。

**反映には Claude Desktop の再起動が要る**（手順6）。このとき
**`python.exe` を手で終了させない。** Claude Desktop が繋ぎ直せずに固まることがある。
必ずトレイの「終了」から Desktop ごと終わらせる。

---

## 付録: この手順を通した環境

2026-09-16 に下記で通している。異なっていても手順は変わらない。

| | |
|---|---|
| OS | Windows 11 Pro |
| Claude Desktop | 2.110.0.0（Microsoft Store / MSIX 版） |
| Python | 3.12.4（`AppData\Local\Programs\Python\Python312`） |
| 依存 | duckdb 1.1.3 / mcp |

掲載した PowerShell コマンドはこの環境で実行して確認している。

---

## 関連

- **[CLAUDE.md](../CLAUDE.md) — 集計を始める前に読む。定義を知らないと間違った数字が出る**
- Mac に入れる手順は [SETUP_MAC.md](SETUP_MAC.md)
- ブラウザの claude.ai から使う手順は [REMOTE_CONNECTOR_MANUAL.md](REMOTE_CONNECTOR_MANUAL.md)、
  その仕組みと構成図は [REMOTE_CONNECTOR.md](REMOTE_CONNECTOR.md)
- 確認用プロンプトの全文と期待値は [VERIFY_PROMPTS.md](VERIFY_PROMPTS.md)
- 質問1つで何が起きるかは [HOW_IT_WORKS.md](HOW_IT_WORKS.md)
