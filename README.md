# BadmintonGPT

以 **nanobot** 為核心的羽球賽事 Agent。使用者在 web UI 提問，Agent 自主路由到：
- **badminton-db MCP**（本地賽事 SQLite，唯讀 `query`/`list_tables`/`describe_table`）
- **badminton-reels MCP**（remote，生成精華短影音）
- **badminton-video-retrieval MCP**（remote，用自然語言檢索既有影片片段）
- **badminton-analyze MCP**（remote，單場比賽的進階數據／戰術分析）
- **web search**（DB 沒有的外部資訊）

每個能力各配一個 **skill playbook**（行為層）；MCP 為存取層。完整設計見 [`docs/DESIGN.md`](./docs/DESIGN.md)，需求脈絡見 [`docs/TASK.md`](./docs/TASK.md)。所有說明文件都收在 [`docs/`](./docs)，repo 根目錄只留 `README.md` 與 `CLAUDE.md`。

## 架構
本 repo 自家的 MCP 都收進 `mcps/`，各自獨立、可分開部署；reels 維持遠端。
```
瀏覽器 ── ws:8765 ── nanobot Agent ──┬─ tools.mcpServers.badminton-db (streamableHttp, SELECT-only) ── badminton-db:8801/mcp ── badminton.db
   (SOUL.md 路由 + skills playbook)  ├─ tools.mcpServers.util (stdio, sleep；in-process)
                                     ├─ tools.mcpServers.badminton-reels (remote streamableHttp + CF Access)
                                     ├─ tools.mcpServers.badminton-video-retrieval (remote streamableHttp + CF Access)
                                     ├─ tools.mcpServers.badminton-analyze (remote streamableHttp + Bearer)
                                     └─ tools.web (duckduckgo) + fetch
```
- **badminton-db**：自家 MCP，現以 **streamable-HTTP** 服務在 `/mcp`（port 8801），自成一個 container；僅在 compose 內網可達、無 auth。設 `MCP_TRANSPORT=stdio` 可改走 stdio（smoke test 用）。
- **util**：sleep MCP，維持 **stdio**，由 gateway in-process 啟動（非獨立 container）。
- **badminton-reels**：維持遠端 streamableHttp（`https://reels-mcp.nycu-adsl.cc/mcp` + CF Access headers），本 repo 不打包它。
- **badminton-video-retrieval**：遠端 streamableHttp（`https://video-retrieval.nycu-cgvlab.org/mcp` + CF Access headers）。
- **badminton-analyze**：遠端 streamableHttp（`https://coachai.cs.nycu.edu.tw/mcp`），**用 bearer token**
  （`${ANALYZE_MCP_TOKEN}`，不是 CF Access）；比賽以 `matches.analyze_match_id` 這個數字 ID 定位。

## 先決條件
- `uv`、Python 3.12、`ffmpeg`（reels 端用，遠端已具備）
- HuggingFace token（已在 `~/.cache/huggingface/token`，供 `ingest.py` 列出 HF 上的 32 場；
  另外 163 場來自 `todo0819/Data-old.zip`，見 `scripts/extract_data_old.py` 與 `CLAUDE.md`）
- **OpenAI API key**：填在本專案 `./.env` 的 `OPENAI_API_KEY=`（必填；不會退回其他專案）
- Cloudflare Access service token：**每個 remote MCP 各一組**，命名 `<NAME>_CF_CLIENT_ID/SECRET`（如 reels 用 `REELS_CF_CLIENT_ID/SECRET`），放本專案 `./.env`
  （例外：`badminton-analyze` 用 bearer token `ANALYZE_MCP_TOKEN`，同樣放 `./.env`）

## 安裝
```bash
# 1) 專案 venv（跑 ingest.py 與 db MCP）
uv sync                       # 建 .venv，裝 mcp / huggingface_hub / pydantic / ...

# 2) nanobot
uv tool install nanobot-ai
nanobot onboard               # 建 ~/.nanobot/{config.json, workspace/}

# 3) 環境變數
cp .env.example .env          # 填入 OPENAI_API_KEY 與 REELS_CF_CLIENT_ID/SECRET
```

## 建資料庫
DB build 已自帶解析（`mcps/badminton-db/ingest_lib/`），只需 HuggingFace token，不再依賴 `badminton-reels` 原始碼。
```bash
.venv/bin/python mcps/badminton-db/ingest.py                 # 產出 data/badminton.db
.venv/bin/python mcps/badminton-db/scripts/verify_db.py      # 對照 ground truth（23 項檢查）
```
- `matches`：全 32 場目錄（27 正式 + 5 NYCU 練習）。
- `rallies`/`shots`：**全部 27 場正式賽事**（從 HF 下載各場標註 CSV，不抓影片；練習片無逐拍）。
- `has_video` 取自 HF `rally_video/` 列表（標註多、實際有影片的回合少）。
- **查特定比賽務必用 `match_name` 篩**（= `matches.name`，不含 .mp4），否則會跨 27 場加總。

## 設定 nanobot
本 repo 已對 `~/.nanobot/config.json` 做的調整：
- `agents.defaults.model="gpt-5.1"`、`provider="openai"`；`providers.openai.apiKey="${OPENAI_API_KEY}"`
- `channels.websocket.enabled=true`（port 8765, `websocketRequiresToken=false`）、`channels.sendToolHints=true`
- `tools.mcpServers`：`badminton-db`（`streamableHttp`，`url` 指向本地 db HTTP server `http://127.0.0.1:8801/mcp`）；`util`（stdio，`command` = `python`、`args` = `mcps/util/server.py`）；`badminton-reels`（遠端 `streamableHttp` + CF Access headers）
- 路由與 DB 速查規則寫在 `~/.nanobot/workspace/SOUL.md`

把 skills **複製**到 nanobot workspace（playbook 漸進揭露）。注意是 `cp` 不是 `ln -s`：
nanobot 的 `restrictToWorkspace` 邊界會先 resolve symlink 再做 containment 檢查，symlink 進來的
skill dir 會 resolve 到 workspace 外的真實路徑，agent 讀 `SKILL.md` 會被擋
（`Path .../SKILL.md is outside allowed directory`）；複製進來才在邊界內。
編輯 `skills/*` 後重跑此 script 再重啟 gateway 即可更新：
```bash
./scripts/sync_skills.sh   # cp -r skills/* → ~/.nanobot/workspace/skills/（會先清掉舊 symlink）
```

## 執行

### 本機 host 模式（開發用）
db MCP 現在是本地 HTTP server，需先在背景跑起來（util 仍由 gateway in-process 啟動，不用手動跑）；
host 的 `~/.nanobot/config.json` 的 `badminton-db` 指向 `http://127.0.0.1:8801/mcp`。
```bash
source scripts/load_env.sh      # 匯出 OPENAI_API_KEY / REELS_CF_* 供 ${VAR} 解析

# badminton-db MCP（HTTP，背景）——服務在 http://127.0.0.1:8801/mcp，並有 GET /healthz
BADMINTON_DB=$PWD/data/badminton.db MCP_HOST=127.0.0.1 .venv/bin/python mcps/badminton-db/server.py &

# Web UI
nanobot gateway                 # 開 http://127.0.0.1:8765

# 或單題（headless）
nanobot agent -m "資料庫裡有哪些 Axelsen 的比賽？"
```

> **host vs container 設定差異**：committed 的 `nanobot/config.json`（template）用的是**容器**的 host/路徑
> （`http://badminton-db:8801/mcp`、stdio util 的 `/app/mcps/util/server.py`）。host 模式的
> `~/.nanobot/config.json` 只需改兩處：`badminton-db` 的 `url` → `http://127.0.0.1:8801/mcp`；`util`
> stdio 的 `args` → 本機絕對路徑的 `mcps/util/server.py`。其餘（model、websocket、reels）兩種模式相同。
>
> **host 模式常見問題**
> - 一律用 `.venv/bin/python`（py3.12，含 `mcp`）；系統 `python3` 是 3.8、沒有 `mcp`。
> - 先把 db MCP（`MCP_HOST=127.0.0.1 … server.py &`）跑起來再 `nanobot gateway`，否則 agent 連不到 DB。
> - `nanobot gateway` 是 in-session 背景程序，session 結束就會死（對外 502/530）——要長駐請走 Docker 部署。
> - 更深入的排錯與 runtime 細節見 `CLAUDE.md`（gotchas / runtime facts）與 `docs/DEPLOY.md`（Docker 排錯）。

### 正式部署（Docker Compose + Cloudflare Tunnel）
對外掛在 `badmintongpt.<zone>` 的可重現部署——`docker compose up` 起三個 service：`gateway`（含自家 fork
的 WebUI，由 `vendor/nanobot/` 建出，內嵌 util stdio MCP）＋ `badminton-db`（自家 HTTP MCP，僅內網
`:8801`）＋ `cloudflared` tunnel；另有 `ingest`（profile）一次性建 DB。`gateway` 經
`depends_on: badminton-db (healthy)` 等 DB 先就緒，agent 的 config/brain 都收進 repo 當 template。
完整步驟（含 Cloudflare 一次性設定、建 DB、驗收）見 **`docs/DEPLOY.md`**。
```bash
cp .env.example .env            # 填 OPENAI_API_KEY / REELS_CF_* / TUNNEL_TOKEN
docker compose --profile ingest run --rm ingest   # 建 ./data/badminton.db（只需 HF_TOKEN）
docker compose up -d --build
docker compose up -d --force-recreate gateway
```

## 驗收（Success Metric）
9 題題庫（對照 `docs/TASK.md` ground truth），檢查工具路由 + 回應：
```bash
.venv/bin/python eval/run_eval.py            # 全 9 題（Q7 會觸發一次遠端剪輯 job）
.venv/bin/python eval/run_eval.py --skip-reels   # 跳過 Q7（不觸發遠端 render）
```

## 檔案
```
mcps/badminton-db/                 # 自家 badminton-db MCP（自成 container，HTTP）
  server.py                        #   FastMCP streamable-http MCP：list_tables/describe_table/query(SELECT-only)，GET /healthz
  ingest.py                        #   HF + 本地 CSV → badminton.db（自帶解析，不再 import badminton-reels）
  ingest_lib/                      #   vendored RallySegment/ShotLabel + parse + 精簡 HF DataLoader（只需 HF_TOKEN）
  scripts/ground_truth.py          #   ground-truth oracle（in-memory）
  scripts/verify_db.py             #   對 badminton.db 斷言 23 項
  scripts/test_db_mcp.py           #   db MCP 獨立 smoke test（MCP_TRANSPORT=stdio）
  scripts/test_decouple_parity.py  #   解耦後與 badminton-reels 解析的 parity 檢查
  Dockerfile / pyproject.toml / README.md
mcps/util/server.py        # util sleep MCP（stdio，gateway in-process 啟動）
skills/badminton-db/       # SKILL.md + references/schema.md（DB playbook）
skills/badminton-reels/    # SKILL.md（reels 非同步編排 playbook）
eval/run_eval.py           # 9 題驗收 harness
scripts/load_env.sh        # 匯出執行所需環境變數
example-mcp-server/        # docs/REMOTE_MCP_SERVER_GUIDE.md 的範例（獨立文件 deliverable，不在 mcps/）
monitoring/gatus/          # Gatus 監控 + 公開狀態頁（單一容器，monitors 用 YAML；見 docs/MONITORING.md）
docs/                      # 所有說明文件（見下）
  DESIGN.md  TASK.md       #   完整設計 / 需求脈絡
  DEPLOY.md                #   Docker Compose + Cloudflare 部署
  MONITORING.md            #   Gatus uptime 監控 + badmintongpt-status.<zone> 公開狀態頁
  ADD_NEW_MCP.md           #   如何新增 MCP（own container HTTP / stdio / skill / 測試）
  MCP_TEST.md              #   mcp_test 用法
  REMOTE_MCP_SERVER_GUIDE.md  #   建 remote MCP 教學（發佈成 docs site）
  REELS_MCP_HANDOFF.md  reels_mcp_usage.md   #   reels 改造規格 / 連線方式
```

新增 MCP 的步驟見 **`docs/ADD_NEW_MCP.md`**（own-container HTTP / stdio / skill playbook / 測試）。
建 remote MCP 給其他子計畫見 **`docs/REMOTE_MCP_SERVER_GUIDE.md`**；驗收任何 MCP server 用 **`docs/MCP_TEST.md`**（`python -m mcp_test <url>`）。

## 已知問題
- `round` 欄位：`Semifinals` 可能被解析成 `Finals`（沿用 reels 的 `_extract_tournament_round`，"Finals" 為 "Semifinals" 子字串）。屬顯示層、不影響 9 題。
- `model="gpt-5.1"` 依 OpenAI 帳號實際可用版本調整。
- 逐拍資料涵蓋 27 場正式賽事；NYCU 5 段練習片只有 `matches` 目錄、無逐拍。查單場數據務必用 `match_name` 篩。
