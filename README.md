# BadmintonGPT

以 **nanobot** 為核心的羽球賽事 Agent。使用者在 web UI 提問，Agent 自主路由到：
- **badminton-db MCP**（本地賽事 SQLite，唯讀 `query`/`list_tables`/`describe_table`）
- **badminton-reels MCP**（remote，生成精華短影音）
- **web search**（DB 沒有的外部資訊）

每個能力各配一個 **skill playbook**（行為層）；MCP 為存取層。完整設計見 [`DESIGN.md`](./DESIGN.md)，需求脈絡見 [`TASK.md`](./TASK.md)。

## 架構
```
瀏覽器 ── ws:8765 ── nanobot Agent ──┬─ tools.mcpServers.badminton-db (stdio, SELECT-only) ── badminton.db
   (SOUL.md 路由 + skills playbook)  ├─ tools.mcpServers.badminton-reels (streamableHttp + CF Access)
                                     └─ tools.web (duckduckgo) + fetch
```

## 先決條件
- `uv`、Python 3.12、`ffmpeg`（reels 端用，遠端已具備）
- HuggingFace token（已在 `~/.cache/huggingface/token`，供 `ingest.py` 列出 32 場）
- **OpenAI API key**：填在本專案 `./.env` 的 `OPENAI_API_KEY=`（必填；不會退回其他專案）
- Cloudflare Access service token：**每個 remote MCP 各一組**，命名 `<NAME>_CF_CLIENT_ID/SECRET`（如 reels 用 `REELS_CF_CLIENT_ID/SECRET`），放本專案 `./.env`

## 安裝
```bash
# 1) 專案 venv（跑 ingest.py 與 db MCP）
uv sync                       # 建 .venv，裝 mcp / huggingface_hub / pydantic / ...

# 2) nanobot
uv tool install nanobot-ai
nanobot onboard               # 建 ~/.nanobot/{config.json, workspace/}

# 3) 環境變數
cp .env.example .env          # 填入 OPENAI_API_KEY 與 CF_ACCESS_CLIENT_ID/SECRET
```

## 建資料庫
```bash
.venv/bin/python ingest.py                 # 產出 data/badminton.db
.venv/bin/python scripts/verify_db.py      # 對照 ground truth（23 項檢查）
```
- `matches`：全 32 場目錄（27 正式 + 5 NYCU 練習）。
- `rallies`/`shots`：**全部 27 場正式賽事**（從 HF 下載各場標註 CSV，不抓影片；練習片無逐拍）。
- `has_video` 取自 HF `rally_video/` 列表（標註多、實際有影片的回合少）。
- **查特定比賽務必用 `match_name` 篩**（= `matches.name`，不含 .mp4），否則會跨 27 場加總。

## 設定 nanobot
本 repo 已對 `~/.nanobot/config.json` 做的調整：
- `agents.defaults.model="gpt-5.1"`、`provider="openai"`；`providers.openai.apiKey="${OPENAI_API_KEY}"`
- `channels.websocket.enabled=true`（port 8765, `websocketRequiresToken=false`）、`channels.sendToolHints=true`
- `tools.mcpServers`：`badminton-db`（本地 stdio，`command` = 本專案 `.venv/bin/python`，`env.BADMINTON_DB` 指向 `data/badminton.db`）；`badminton-reels`（`streamableHttp` + CF Access headers）
- 路由與 DB 速查規則寫在 `~/.nanobot/workspace/SOUL.md`

把 skills 連到 nanobot workspace（playbook 漸進揭露）：
```bash
ln -sfn "$PWD/skills/badminton-db"    ~/.nanobot/workspace/skills/badminton-db
ln -sfn "$PWD/skills/badminton-reels" ~/.nanobot/workspace/skills/badminton-reels
```

## 執行
```bash
source scripts/load_env.sh      # 匯出 OPENAI_API_KEY / CF_ACCESS_* 供 ${VAR} 解析

# Web UI
nanobot gateway                 # 開 http://127.0.0.1:8765

# 或單題（headless）
nanobot agent -m "資料庫裡有哪些 Axelsen 的比賽？"
```

## 驗收（Success Metric）
9 題題庫（對照 `TASK.md` ground truth），檢查工具路由 + 回應：
```bash
.venv/bin/python eval/run_eval.py            # 全 9 題（Q7 會觸發一次遠端剪輯 job）
.venv/bin/python eval/run_eval.py --skip-reels   # 跳過 Q7（不觸發遠端 render）
```

## 檔案
```
ingest.py                  # HF + 本地 CSV → badminton.db（重用 ../badminton-reels 解析）
db_mcp/server.py           # 本地 stdio MCP：list_tables/describe_table/query(SELECT-only)
skills/badminton-db/       # SKILL.md + references/schema.md（DB playbook）
skills/badminton-reels/    # SKILL.md（reels 非同步編排 playbook）
eval/run_eval.py           # 9 題驗收 harness
scripts/ground_truth.py    # ground-truth oracle（in-memory）
scripts/verify_db.py       # 對 badminton.db 斷言 22 項
scripts/test_db_mcp.py     # db MCP 獨立 smoke test
scripts/load_env.sh        # 匯出執行所需環境變數
```

新增 MCP 的步驟見 **`ADD_NEW_MCP.md`**（本地 stdio / remote HTTP / skill playbook / 測試）。
建 remote MCP 給其他子計畫見 **`REMOTE_MCP_SERVER_GUIDE.md`**；驗收任何 MCP server 用 **`MCP_TEST.md`**（`python -m mcp_test <url>`）。

## 已知問題
- `round` 欄位：`Semifinals` 可能被解析成 `Finals`（沿用 reels 的 `_extract_tournament_round`，"Finals" 為 "Semifinals" 子字串）。屬顯示層、不影響 9 題。
- `model="gpt-5.1"` 依 OpenAI 帳號實際可用版本調整。
- 逐拍資料涵蓋 27 場正式賽事；NYCU 5 段練習片只有 `matches` 目錄、無逐拍。查單場數據務必用 `match_name` 篩。
