# claude.ai から使う（リモートコネクタ）— 手動手順・このPC用

`docs/REMOTE_CONNECTOR.md` の内容を、**このPCで手を動かす順**に並べ直したもの。
仕組みの説明は元の文書にあるので、ここは操作に必要なことだけ書く。

対象は**経路B（claude.ai）だけ**。経路A（Claude Desktop）は Desktop が
`server.py` を勝手に起動するので手順は要らない。両者は別プロセスなので、
**Bをやっている間もAはそのまま動く。止める必要はない。**

---

## 事前確認（2026-09-16 実測・すべて済み）

| 項目 | 状態 |
|---|---|
| cloudflared | `2026.9.1` / `C:\Program Files (x86)\cloudflared\cloudflared.exe` |
| Python | `3.12.4` / `C:\Users\yshiw\AppData\Local\Programs\Python\Python312\python.exe` |
| 依存 | `duckdb 1.1.3` / `mcp` 導入済み |
| ポート 8000 | 空き |
| `curl.exe` | `C:\Windows\system32\curl.exe`（PowerShell の `curl` は別物。`.exe` を付ける） |
| 経路A（Desktop） | 接続確認済み |

**インストールも `pip install` も要らない。** 下の手順をそのまま実行できる。

## 用意するもの

**ターミナル3枚**（PowerShell）。

| | 用途 | 動き |
|---|---|---|
| ① | cloudflared | 繋ぎっぱなし。閉じるとトンネルが切れる |
| ② | server.py | 繋ぎっぱなし。閉じるとサーバーが落ちる |
| ③ | 疎通確認 | 一時的。確認が終わったら閉じてよい |

①②は**終わるまで閉じない**。

---

## 手順

### 1. ターミナル① — トンネルを立てる

```powershell
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://127.0.0.1:8000
```

数秒待つと、枠で囲まれた URL が出る。

```
+--------------------------------------------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):   |
|  https://organisation-dennis-book-curve.trycloudflare.com                                   |
+--------------------------------------------------------------------------------------------+
```

- **ホスト名は起動のたびに変わる。** 上の例（`organisation-dennis-book-curve`）は
  そのまま使えない。自分の画面に出たものを使う
- `--url http://localhost:8000` と書かない。`localhost` が IPv6 の `::1` に解決されて、
  127.0.0.1 で待っているサーバーに届かず 502 になることがある
- この時点ではまだサーバーが居ないので、URL を開いても 502。それで正常

`Registered tunnel connection ... location=nrt09 protocol=quic` が出ればトンネルは確立している
（`nrt` は成田のエッジ）。UDP が塞がれている環境では `protocol=http2` に落ちるが、動作は同じ。

### 2. ホスト名を控える

URL から `https://` と末尾を除いた**ホスト名だけ**を次で使う。

```
organisation-dennis-book-curve.trycloudflare.com
```

### 3. ターミナル② — サーバーを起動する

`<ホスト名>` を手順2のものに置き換える。

```powershell
cd C:\Users\yshiw\Documents\GIS\npa\npa-traffic-accident-analytics
python mcp_server\server.py --http --port 8000 --allow-host <ホスト名>.trycloudflare.com
```

こう出れば起動している。

```
allowed hosts: ['<ホスト名>.trycloudflare.com']
MCP endpoint: http://127.0.0.1:8000/mcp
StreamableHTTP session manager started
```

**`--allow-host` を省くと全リクエストが弾かれる。** DNS リバインディング対策の
Host ヘッダ検証が効いていて、既定では `localhost` と `127.0.0.1` しか通らない。
トンネル越しに来るリクエストの Host は `<ホスト名>.trycloudflare.com` なので、
明示的に許可が要る。トンネルのホスト名が分かってからでないと書けないため、
**1 → 3 の順になる**（逆順にはできない）。

### 4. ターミナル③ — 疎通確認

claude.ai に登録する前に、**公開URLで実際に応答が返るか**をここで確かめる。
ここが通らないまま登録しても繋がらない。

```powershell
curl.exe -s -i -X POST https://<ホスト名>.trycloudflare.com/mcp `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -d '{\"jsonrpc\":\"2.0\",\"id\":0,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-06-18\",\"capabilities\":{},\"clientInfo\":{\"name\":\"smoke\",\"version\":\"0\"}}}'
```

このコマンドは PowerShell 5.1 で動作確認済み。バッククォート（`` ` ``）は行継続、
JSON 内の `\"` は PS 5.1 がネイティブ exe に渡すときに必要なエスケープなので、
**どちらも消さない**。1行で書く場合はバッククォートだけ外す。

**成功の目印**はこの3つ。

```
HTTP/1.1 200 OK
mcp-session-id: <32桁の16進>
event: message
data: {"jsonrpc":"2.0","id":0,"result":{...,"serverInfo":{"name":"npa-traffic-accident",...}}}
```

`serverInfo.name` が `npa-traffic-accident` なら、Anthropic 側から届く経路と同じ道が通っている。
失敗した場合は下の「つまずいたとき」へ。

### 5. claude.ai に登録する

**組織設定（Organization settings）→ コネクタ → カスタムコネクタを追加。**
個人の設定画面には出ない。

| 項目 | 値 |
|---|---|
| 名前 | 任意（例: `npa-traffic-accident`） |
| URL | `https://<ホスト名>.trycloudflare.com/mcp` |
| OAuth Client ID / Secret | **空のまま**。認証は設定不要 |

- **末尾の `/mcp` を忘れない。** ルート（`/`）は 404
- **Team / Enterprise でカスタムコネクタを追加できるのは組織の Owner だけ。**
  「カスタムコネクタを追加」が見当たらないなら権限がない。会社アカウント（Team/Enterprise）で
  試す場合はここで止まる可能性がある。
  個人アカウントの claude.ai なら自分で追加できる（2026-09-15 に確認済みの経路はこちら）

登録後、**新しい会話**を開いてこのコネクタを有効にする。

### 6. 動作確認

`docs/VERIFY_PROMPTS.md` の 1〜8 を上から貼る。最初の2つだけ再掲する。

```
生活道路の事故件数を年別に出して。厳密定義で。
```

→ `seikatsu_dashboard`（strict）。2019年 65,188 件 … 2024年 45,296 件。
グラフ付きのビューが出れば描画 OK。

```
新宿駅から半径1kmの2024年の生活道路の事故を地図に出して。中心は 35.6896, 139.7006。
```

→ `accident_map`。**該当 82 件・描画 82 件**。背景の地理院ベクトルタイル（淡色）まで
出れば `_meta.ui.csp` の外部ドメイン宣言も効いている。点だけで背景が白いなら CSP を疑う。

4〜8 はガードレールの確認で、**それらしい数字が返ってきたら不合格**という読み方をする。

### 7. 終了と後始末

**この順で**行う。

1. **claude.ai からコネクタを削除する** — URL は次回変わるので、残しても繋がらない死んだ設定になる
2. **ターミナル②で Ctrl+C**（サーバー）
3. **ターミナル①で Ctrl+C**（トンネル）

残っていないかの確認と、強制終了。

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
Get-Process cloudflared -ErrorAction SilentlyContinue

taskkill /IM cloudflared.exe /F
taskkill /PID <OwningProcess> /F
```

**経路A（Claude Desktop）はこの後始末の影響を受けない。** 止まるのは claude.ai からの経路だけ。

---

## つまずいたとき

| 症状 | 原因 | 対処 |
|---|---|---|
| `502 Bad Gateway` | サーバーがまだ起動していない／`--url localhost:8000` で立てて `::1` に行った | 手順3を先に確認。トンネルは `127.0.0.1` で立て直す |
| `400` / `Invalid Host header` | `--allow-host` が無い・ホスト名が違う | 手順1で出た URL と完全一致か確認。トンネルを立て直したら**ホスト名は変わっている** |
| `404` | URL 末尾の `/mcp` が無い | `https://<ホスト名>/mcp` にする |
| サーバーが起動せず `address already in use` | 8000 番が使用中 | `Get-NetTCPConnection -LocalPort 8000 -State Listen` で PID を見て `taskkill /PID <PID> /F`、または `--port 8001` にしてトンネルも合わせる |
| claude.ai に「カスタムコネクタを追加」が無い | 組織の Owner ではない | 個人アカウントで試すか、Owner に追加してもらう |
| ツールは見えるがビューが出ず数字だけ | ホストが MCP Apps をネゴシエートしていない | claude.ai / Claude Desktop なら描画される。ターミナルの Claude Code は数字だけ（集計としては正常） |
| 地図は出るが背景が白い | `_meta.ui.csp` の外部ドメイン宣言が通っていない | サーバー側の CSP 宣言を確認 |
| しばらく放置したら繋がらなくなった | PC のスリープ等でトンネルが切れた | ①②を立て直す。**ホスト名が変わるので claude.ai の URL も登録し直す** |

## 注意

- **URL は毎回変わる。** PC を落とす・トンネルを張り直すたびに別のホスト名になる。
  恒久運用には使えない（固定URL・PC非依存は issue #3）
- **公開中は `run_sql`（任意の SELECT を通す口）も外から叩ける。** URL を知られない限り
  届かず、読み取り専用の公開データなので実害は考えにくいが、**立てっぱなしにしない**
- **Claude Desktop 側でこのリモートコネクタを有効にしない。** 開発者タブの stdio と
  同じツールが2組並んで紛らわしくなる。確認中は claude.ai だけで有効にする
- Anthropic 側から公開インターネット経由で到達できる必要がある。社内網・VPN の内側は不可
- サーバーのコードを変えた場合、**経路B は②を再起動すれば反映される**が、
  **経路A は Claude Desktop 自体の再起動が要る**（子プロセスだけ落とすと繋ぎ直せない）

---

## 関連

- 仕組みと構成図、経路A/Bの違いは [REMOTE_CONNECTOR.md](REMOTE_CONNECTOR.md)
- 動作確認プロンプトの全文と期待値は [VERIFY_PROMPTS.md](VERIFY_PROMPTS.md)
- 恒久ホスティング（固定URL・PC非依存）は issue #3
