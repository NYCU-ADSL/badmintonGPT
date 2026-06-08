# BadmintonGPT — 系統設計 (DESIGN)

> 本文件描述 BadmintonGPT 的**詳細架構**與**實作方式（how to write it）**。
> 需求脈絡見 [`TASK.md`](./TASK.md)。
> **reels MCP server 已完成並上線**（remote，`https://reels-mcp.nycu-adsl.cc`，CF Access 保護）；本文件把它當成**外部既有服務**，連線方式見 [`reels_mcp_usage.md`](./reels_mcp_usage.md)，其內部改造規格見 [`REELS_MCP_HANDOFF.md`](./REELS_MCP_HANDOFF.md)。

> 📌 **想知道「實際做出來、已驗證」的現況**（而非提案）？直接看文末
> [已實作並驗證（nanobot v0.2.1）](#已實作並驗證nanobot-v0212026-06-06)。

## 目錄

1. [目的與範圍](#1-目的與範圍)
2. [系統總覽](#2-系統總覽)
3. [元件詳細設計](#3-元件詳細設計)
4. [關鍵資料流（Sequence）](#4-關鍵資料流sequence)
5. [安全與部署](#5-安全與部署)
6. [實作步驟（how to write it）](#6-實作步驟how-to-write-it建議順序)
7. [測試與驗收（Success Metric）](#7-測試與驗收success-metric)
8. [已確認的決策](#8-已確認的決策前述問題已拍板)
9. [已實作並驗證（nanobot v0.2.1）](#已實作並驗證nanobot-v0212026-06-06)

---

## 1. 目的與範圍

打造一個以 **nanobot** 為核心的羽球 Agent，使用者在 web UI 提問後，Agent 自行決定呼叫：
- **SQLite 賽事 DB**（text-to-SQL，查選手/比賽/逐拍統計、找戰術回合片段）
- **reels MCP**（生成精華短影音，非同步）
- **web search**（DB 沒有的外部資訊）

本文件涵蓋四個**仍需實作**的部分（reels MCP 不在內，已完成）：
1. nanobot Agent 設定與工具路由策略
2. SQLite DB schema 與 ingestion
3. DB 存取機制（**本地 `badminton-db` MCP**：`list_tables`/`describe_table`/`query`(SELECT-only) ＋ **`badminton-db` skill**：playbook）
4. Web UI 與 Success-Metric 驗收 harness

| 元件 | 狀態 | 本文件章節 |
|------|------|-----------|
| reels MCP server | ✅ 已完成、已部署 | §3.4（契約/整合） |
| reels skill playbook | ⬜ 待做 | §3.4.1 |
| nanobot Agent 設定 | ⬜ 待做 | §3.1 |
| SQLite DB + ingestion | ⬜ 待做（matches=全32、shots=本地1場） | §3.2 |
| DB 存取（本地 `badminton-db` MCP + skill playbook） | ⬜ 待做 | §3.3 |
| web search | ⬜ 待做（開設定即可） | §3.5 |
| Web UI（nanobot 內建） | ⬜ 待做（開設定即可） | §3.6 |
| 驗收 harness | ⬜ 待做 | §7 |

---

## 2. 系統總覽

```
                                  ┌──────────────────────────────────────┐
                                  │            使用者 (瀏覽器)             │
                                  └───────────────────┬──────────────────┘
                                  WebSocket (ws://127.0.0.1:8765, 經 cloudflared tunnel)
                                                      │
                          ┌───────────────────────────▼───────────────────────────┐
                          │      nanobot Agent loop（gateway 容器：純 host）         │
                          │  providers(可切換) · SOUL.md(精簡路由)                   │
                          │  skills(playbooks)：badminton-db/badminton-reels/        │
                          │                     long-mcp-job                          │
                          │  util MCP (stdio, in-process：sleep)                      │
                          └──────┬───────────────┬──────────────────┬──────────────┘
                       streamableHttp        streamableHttp        tools.web
                       (compose 內網)         (CF Access)           │ (search+fetch)
                ┌──────────┴───────────┐  ┌──────┴──────────────┐  ┌──┴───────────┐
                ▼                      │  ▼                     │  ▼              │
   ┌───────────────────────────────┐  │ ┌──────────────────────┴┐ ┌─────────────┐
   │ badminton-db MCP（自有容器）   │  │ │ reels MCP (remote,已做)│ │ Web Search  │
   │ FastMCP streamable-http       │  │ │ generate_reel /        │ │ (duckduckgo)│
   │ http://badminton-db:8801/mcp  │  │ │ get_reel_status /      │ └─────────────┘
   │  list_tables / describe_table │  │ │ get_reel_result /      │
   │  / query (SELECT-only)        │  │ │ GET /files/{id}.mp4    │
   │  + GET /healthz               │  │ └──────────▲─────────────┘
   └────────────▲──────────────────┘  │            │ 共用同一份資料來源
                │                      │            │
   ┌────────────┴──────────────┐  ingest 容器  ┌───┴────────────────────────┐
   │  badminton.db (SQLite)    │◀─(profile)────│  HuggingFace dataset        │
   │  matches/rallies/shots    │  ingest_lib   │  howard9199/Badminton       │
   └───────────────────────────┘  (reels-解耦) └─────────────────────────────┘
```

> 部署形態：每支「本 repo 自有」MCP 各自為政——`badminton-db` 是**獨立容器**，以
> streamable-HTTP 對 compose 內網提供 `http://badminton-db:8801/mcp`（無 auth，永不對外）；
> `util` 仍是 **stdio**、由 gateway in-process 啟動（非獨立容器）；`reels` 維持 **remote**
> （`https://reels-mcp.nycu-adsl.cc/mcp`，CF Access）。DB 建置（ingest 容器，profile）已與
> badminton-reels **解耦**，解析/模型 vendored 在 `mcps/badminton-db/ingest_lib/`，只需 `HF_TOKEN`。

**設計原則**
- **單一資料真相**：DB ingestion 與 reels 都源自同一個 HF dataset。解析邏輯（選手 A/B、rally_id 格式）原本重用 badminton-reels，**現已 vendored 進 `mcps/badminton-db/ingest_lib/`**（與 reels 解析行為一致，parity 測試把關），ingest 不再 import badminton-reels。
- **MCP 連接層 + skill playbook 層（2026 主流 hybrid）**：所有資料/工具存取走 **MCP**——`badminton-db`（自有容器、streamable-HTTP `:8801/mcp`）與 `badminton-reels`（remote）；**每個能力各配一個 skill playbook**（`badminton-db`、`badminton-reels`），只放「何時用、慣例、要呼叫哪個 MCP 工具、怎麼編排」，不負責存取本身。「MCP scale 系統、skill scale 行為」。
- **DB 存取確定路由**：DB 查詢是 MCP `query` 工具（typed、可稽核），不靠 exec 跑 CLI；安全（SELECT-only + `mode=ro`）由 MCP server 內建。
- **Agent 自主路由**：system prompt 留精簡路由提示；DB playbook（skill）提供細節，實際存取由 MCP 工具確定執行。

---

## 3. 元件詳細設計

### 3.1 nanobot Agent

#### 3.1.1 `~/.nanobot/config.json`（完整範例）

```jsonc
{
  "providers": {
    // 預設 OpenAI；apiKey 用 ${ENV} 注入。要切其他家再加（仍可切換）。
    "openai": { "apiKey": "${OPENAI_API_KEY}" }
  },

  "agents": {
    "defaults": {
      "modelPreset": "deep",
      "fallbackModels": ["fast"],
      "temperature": 0.1,           // text-to-SQL 要穩定，低溫
      "reasoningEffort": "medium",
      "timezone": "Asia/Taipei"
    }
  },
  "modelPresets": {
    // 皆 OpenAI；model 名稱依實際可用版本調整（badminton-reels 目前用 gpt-5.1）
    "deep": { "provider": "openai", "model": "gpt-5.1",      "reasoningEffort": "high" },
    "fast": { "provider": "openai", "model": "gpt-5.1-mini", "temperature": 0.2 }
  },

  "channels": {
    "sendProgress": true,
    "sendToolHints": true,          // 驗收 harness 需要看到工具呼叫
    "websocket": { "enabled": true, "port": 8765 }
  },

  // mcpServers（頂層）：DB MCP（自有容器、streamable-HTTP）+ remote reels MCP（streamableHttp，usage.md 已實測）
  "mcpServers": {
    "badminton-db": {
      "type": "streamableHttp",
      "url": "http://badminton-db:8801/mcp",
      "enabledTools": ["list_tables", "describe_table", "query"]
      // 獨立容器、streamable-HTTP；無 auth（僅 compose 內網，永不對外）；
      // 曝露 list_tables / describe_table / query(SELECT-only) + GET /healthz（見 §3.3）
    },
    "util": {
      "type": "stdio",
      "command": "python3",
      "args": ["/app/mcps/util/server.py"],
      "enabledTools": ["sleep"],
      "toolTimeout": 70
      // stdio、由 gateway in-process 啟動（非獨立容器）；單一 sleep(seconds≤60) 工具，供 async-job 輪詢節流
    },
    "badminton-reels": {
      "type": "streamableHttp",
      "url": "https://reels-mcp.nycu-adsl.cc/mcp",
      "headers": {
        "CF-Access-Client-Id": "${REELS_CF_CLIENT_ID}",
        "CF-Access-Client-Secret": "${REELS_CF_CLIENT_SECRET}"
      },
      "toolTimeout": 120,
      "enabledTools": ["generate_reel", "get_reel_status", "get_reel_result"]
    }
  },

  "tools": {
    "web": {
      "enable": true,
      "search": { "provider": "duckduckgo" },   // 免金鑰，開箱即用
      "fetch":  { "useJinaReader": true }
    }
    // 不需 exec：DB 走 badminton-db MCP；skill 僅為 playbook（無腳本要跑）
  }
}
```

> reels 用 `type:streamableHttp`（remote，CF Access，已實測）；`badminton-db` 同樣是 `type:streamableHttp`，但指向 compose 內網的自有容器 `http://badminton-db:8801/mcp`（無 auth、永不對外）；`util` 是 in-process stdio。**host/dev 模式**：DB MCP 改以 `MCP_HOST=127.0.0.1 python mcps/badminton-db/server.py` 在本機跑 HTTP，host 的 `~/.nanobot/config.json` 把 `badminton-db` 指向 `http://127.0.0.1:8801/mcp`，util 維持 stdio（`python mcps/util/server.py`）。
> **skill 探索路徑**：nanobot 從 workspace 的 `skills/`（DeepWiki 記載）或 `~/.nanobot/skills/` 自動發現 `badminton-db` playbook skill；實際探索位置需依 nanobot 版本確認（見 §8）。

#### 3.1.2 環境變數（`.env` / systemd EnvironmentFile）
```
OPENAI_API_KEY=...
REELS_CF_CLIENT_ID=...           # reels MCP 的 Cloudflare Access service token
REELS_CF_CLIENT_SECRET=...
HF_TOKEN=...                     # 僅 ingest 容器需要（DB 建置）
BADMINTONGPT_HOME=/mnt/ssd1/howchien/badmintonGPT   # 專案根目錄
```
- gateway 容器**不再**設 `BADMINTON_DB`——DB 已搬進 `badminton-db` 容器（由該容器自帶 `BADMINTON_DB` 指向掛載的 `data/badminton.db`），gateway 只透過 HTTP 連它。
- ingest 容器（DB 建置）**只需 `HF_TOKEN`**；不再需要 `REELS_SRC` / `REELS_SRC_HOST`（已從 `.env.example`/compose 移除，見 §3.2.2 解耦）。
- nanobot 啟動前需先載入這些變數（systemd `EnvironmentFile=`、direnv、或 `--env-file`）。

#### 3.1.3 System Prompt（精簡路由）
**細節都放進對應的 skill playbook**——DB schema/enum → `badminton-db` skill（§3.3）；reels 非同步編排/慣例 → `badminton-reels` skill（§3.4.1）。system prompt 只留**人設 + 路由提示**（省 context）：

```
你是 BadmintonGPT，服務對象：一般觀眾、教練、選手。

路由原則：
1) 任何牽涉「資料庫內既有賽事數據」的問題（選手有哪些比賽、球種次數、得失分原因、
   比分、含特定戰術/球種的回合片段）—— 參考 badminton-db skill（playbook：enum 值、
   A/B 對照、範例），再呼叫 badminton-db MCP 的 query/list_tables/describe_table 工具
   （query 只接受單句 SELECT；回合片段須過濾 has_video=1）。
2) 使用者要「做一支精華/highlight 影片」—— 參考 badminton-reels skill（playbook：非同步
   編排、match_name 慣例、video_url 呈現），再呼叫 reels MCP 的 generate_reel /
   get_reel_status / get_reel_result。
3) DB 沒有的外部資訊（最新世界排名、選手近況、賽事新聞）—— 用 web search。

回答原則：先說結論，附上關鍵數字；需要時列出依據的 SQL 或來源連結。
```

> 設計重點：schema/enum 這類「只有 DB 問題才需要」的內容放在 skill playbook（漸進揭露），不常駐 system prompt；實際存取則由 `badminton-db` MCP 工具確定執行（不靠 skill 觸發成敗）。

---

### 3.2 SQLite 賽事 DB

#### 3.2.1 Schema（DDL）

```sql
CREATE TABLE matches (
  folder       TEXT PRIMARY KEY,   -- HF 資料夾名（含 .mp4 後綴）
  name         TEXT,               -- 去後綴的可讀名
  tournament   TEXT,               -- 由名稱解析（可空）
  round        TEXT,               -- Finals/Semifinals…（可空）
  player_a     TEXT,               -- 對應 shots.player='A'
  player_b     TEXT,               -- 對應 shots.player='B'
  year         INTEGER,            -- 皆 2022
  is_practice  INTEGER DEFAULT 0   -- NYCU_Other_practice* = 1
);

CREATE TABLE rallies (
  match_folder   TEXT REFERENCES matches(folder),
  rally_id       TEXT,             -- "set_scoreA_scoreB"，如 1_05_04
  set_no         INTEGER,
  score_a        INTEGER,
  score_b        INTEGER,
  start_frame    INTEGER,
  end_frame      INTEGER,
  has_video      INTEGER DEFAULT 0,-- rally_video/ 是否真有此檔（關鍵！）
  video_filename TEXT,             -- 例 1_05_04.mp4（has_video=1 時）
  PRIMARY KEY (match_folder, rally_id)
);

CREATE TABLE shots (
  match_folder    TEXT REFERENCES matches(folder),
  set_no          INTEGER,
  rally           INTEGER,         -- 該 set 內第幾個 rally
  ball_round      INTEGER,
  player          TEXT,            -- 'A'|'B'
  server          TEXT,
  type            TEXT,            -- 球種（中文 enum）
  aroundhead      INTEGER,
  backhand        INTEGER,
  hit_area        INTEGER,
  landing_area    INTEGER,
  lose_reason     TEXT,
  win_reason      TEXT,
  getpoint_player TEXT,            -- 'A'|'B'
  roundscore_a    INTEGER,
  roundscore_b    INTEGER
  -- 其餘座標欄（hit_x/y, landing_x/y, location_*）按需再加
);

-- 建議索引
CREATE INDEX idx_shots_match_type    ON shots(match_folder, type);
CREATE INDEX idx_shots_match_player  ON shots(match_folder, player);
CREATE INDEX idx_rallies_match_video ON rallies(match_folder, has_video);
```

#### 3.2.2 Ingestion（`mcps/badminton-db/ingest.py`）設計

職責：把 HF dataset → `badminton.db`。**已與 badminton-reels 解耦**：原本靠 `sys.path` 注入
`$REELS_SRC` 並 `import badminton.data_loader / badminton.models` 的作法已移除；解析邏輯與資料模型
（`RallySegment`/`ShotLabel`、`parse.extract_tournament_round`、薄薄一層 HF `DataLoader`）**vendored
在 `mcps/badminton-db/ingest_lib/`**，`ingest.py` 改 `from ingest_lib import ...`。因此 DB 建置**只需
`HF_TOKEN`**，不需要 `OPENAI_API_KEY` / Fish 等 reels 相依，也不需要 badminton-reels 原始碼在機器上。
`REELS_SRC` / `REELS_SRC_HOST` 已從 `.env.example` 與 compose ingest service 移除。一次性建置：
`docker compose --profile ingest run --rm ingest`（跑在 `badmintongpt-db` 映像上，產出 `./data/badminton.db`）。

**本階段範圍（已確認）**：逐拍重資料（`rallies` + `shots`）**只先做本地已下載的那 1 場**（Axelsen vs Lee）。但 `matches` 目錄表用**完整 32 場名稱**填（只需 HF 檔案清單、不必下載），這樣測試題庫的 Q1（Axelsen 有哪些比賽）、Q9（年份/等級）仍可正確回答。

步驟：
1. `matches` 目錄（全 32）：用 `huggingface_hub.HfApi().list_repo_files("howard9199/Badminton")` 取得 32 個資料夾名（**不下載內容**），逐筆寫入 `matches`：
   - `folder`（含 .mp4）、`name`（去 .mp4，**即傳給 reels 的 `match_name`**）；
   - `tournament`/`round`：用 vendored `ingest_lib.parse.extract_tournament_round()`；
   - `is_practice = name.startswith("NYCU_Other_practice")`、`year=2022`；
   - 選手姓名：能從名稱解析者填 `player_a/player_b`，practice 片可留空。
2. 逐拍資料（本地有下載者，目前 1 場）：對每個**本地存在**的 match 資料夾：
   - 用 vendored `ingest_lib` 的 HF `DataLoader` + `RallySegment`/`ShotLabel` 模型取得該場
     `rally_segments` 與逐 set `labels`，回填該場 `matches.player_a/b` 並確保 A/B↔姓名、rally_id
     格式與既有 reels 慣例一致（模型本身即由 reels 那份 vendored 過來，故維持一致）。
   - 寫 `rallies`：來自 `RallySeg.csv`；`has_video`/`video_filename` 由掃 `rally_video/*.mp4` 判定（**只有部分回合有檔**）。
   - 寫 `shots`：攤平 `label/set{1,2,3}.csv`，欄位對映見 DDL。
3. 用 transaction、`INSERT OR REPLACE`，可重跑（idempotent）；自動偵測哪些 match 有本地資料。
4. CLI：`python mcps/badminton-db/ingest.py --db $BADMINTON_DB [--catalog-only] [--only <folder>]`。日後要擴到全 27/32 場，加 HF 下載即可（只需 `HF_TOKEN`）。

**A/B ↔ 姓名映射**：用 `ingest.py:derive_ab`（A = 資料夾名最先出現的選手名，case/underscore-insensitive 比對），不要用 `DataLoader._extract_players`（它回傳第一個 rally 的上/下半場，會隨局數翻面）。

> 已用本地唯一完整下載的 Axelsen vs Lee 驗證過欄位與值（1213 筆 shots，A=Viktor AXELSEN、B=LEE Zii Jia）；ground truth 重跑見 `mcps/badminton-db/scripts/ground_truth.py`（其作法正是「matches=全32、shots=本地1場」）。解耦後另有 `mcps/badminton-db/scripts/test_decouple_parity.py` 比對 vendored 解析與原 reels 解析輸出一致（parity OK）。

---

### 3.3 DB 存取（本地 `badminton-db` MCP + `badminton-db` skill playbook）

決策（2026 主流 hybrid）：DB 存取做成**自有容器的 streamable-HTTP MCP**（typed/有護欄的工具 → 確定路由、可稽核；nanobot 以 `http://badminton-db:8801/mcp` 連接）；**skill 只當 playbook**（何時用、enum、A/B、範例、要呼叫哪個工具），不負責存取本身。reels 也走 MCP——兩者都在連接層，skill 在行為層。

#### 3.3.1 `badminton-db` MCP server（自有容器、streamable-HTTP）
曝露三個工具：

| 工具 | 輸入 | 輸出 | 用途 |
|------|------|------|------|
| `list_tables` | — | 表名清單 | 讓 agent 探索結構 |
| `describe_table` | `table` | 欄位/型別 | 取代把整份 schema 塞 prompt |
| `query` | `sql`（單句 SELECT） | `{rows, row_count}` | 實際查詢；SELECT-only + `mode=ro` |

server 骨架（FastMCP，預設以 streamable-HTTP 在 `:8801/mcp` 對外，外加 `GET /healthz`；
內建 SELECT-only 護欄）。設 `MCP_TRANSPORT=stdio` 可改跑 stdio（smoke test 用）：
```python
#!/usr/bin/env python3
# mcps/badminton-db/server.py —— streamable-HTTP MCP：list_tables / describe_table / query(SELECT-only)
import os, re, sqlite3
from starlette.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

# host/port 由 env 注入（容器內 0.0.0.0:8801；host/dev 用 MCP_HOST=127.0.0.1）
mcp = FastMCP("badminton-db",
              host=os.environ.get("MCP_HOST", "0.0.0.0"),
              port=int(os.environ.get("MCP_PORT", "8801")))

def _ro():
    db = sqlite3.connect(f"file:{os.environ['BADMINTON_DB']}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db

@mcp.tool()
def list_tables() -> list[str]:
    with _ro() as db:
        return [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")]

@mcp.tool()
def describe_table(table: str) -> list[dict]:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        return [{"error": "bad table name"}]
    with _ro() as db:
        return [dict(r) for r in db.execute(f"PRAGMA table_info({table})")]

@mcp.tool()
def query(sql: str) -> dict:
    """只接受單句 SELECT，回 {rows, row_count}（上限 200 列）。"""
    if not re.match(r"^\s*select\b", sql, re.I) or ";" in sql.rstrip().rstrip(";"):
        return {"error": "only a single SELECT is allowed"}
    with _ro() as db:
        try:
            rows = [dict(r) for r in db.execute(sql).fetchmany(200)]
            return {"rows": rows, "row_count": len(rows)}
        except Exception as e:
            return {"error": str(e)}

# 給 compose healthcheck / depends_on: service_healthy 用
@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_req):
    return JSONResponse({"ok": True})

if __name__ == "__main__":
    if os.environ.get("MCP_TRANSPORT") == "stdio":
        mcp.run()                              # stdio（smoke test）
    else:
        mcp.run(transport="streamable-http")   # 預設：HTTP 在 :8801/mcp
```
- 安全：`mode=ro` + `query` SELECT-only 雙重保險；**MCP server 即安全邊界**（不靠 exec/CLI）。
  端點**只在 compose 內網**（`http://badminton-db:8801/mcp`），無 auth、永不對外發佈 port、永不過 tunnel。
- 容器：`mcps/badminton-db/Dockerfile`（映像 `badmintongpt-db:0.1.0`，compose service `badminton-db`），
  `data/badminton.db` 以 volume 掛入；`/healthz` 餵 compose healthcheck，gateway 以
  `depends_on: { badminton-db: { condition: service_healthy } }` 等它就緒。
- 註冊：見 §3.1.1 `mcpServers.badminton-db`（`type:streamableHttp` + `url`）。

#### 3.3.2 `badminton-db` skill（playbook，非存取手段）
skill 只放「怎麼用得好」的領域知識，觸發後引導 agent 呼叫上面的 MCP 工具。

```
${BADMINTONGPT_HOME}/skills/badminton-db/
├── SKILL.md
└── references/
    └── schema.md     # enum 值、A/B↔姓名、rally_id/has_video 規則、範例 SQL
```

`SKILL.md`：
```markdown
---
name: badminton-db
description: 查羽球賽事資料庫（選手有哪些比賽、逐拍統計如球種次數/得失分原因、比分、
  含特定戰術球種的回合片段）。當問題牽涉資料庫內既有賽事數據時，參考本 playbook 後呼叫
  badminton-db MCP 工具。
---

# 怎麼查
1. 需要時先用 describe_table 看欄位；用 query 下**單句 SELECT** 取數。
2. 回合片段：query 時務必 `WHERE has_video=1`，只回實際有影片的 rally。
3. 球種/得失分原因為中文 enum、A/B↔姓名對照、rally_id 格式 → 見 references/schema.md。

# 常見查詢
- 某選手有哪些比賽：query("SELECT name FROM matches WHERE name LIKE '%AXELSEN%'")
- 球種得分數：     query("SELECT COUNT(*) FROM shots WHERE type='殺球' AND player='A' AND win_reason<>''")
- 失分原因分布：   query("SELECT lose_reason, COUNT(*) n FROM shots WHERE lose_reason<>'' GROUP BY 1 ORDER BY n DESC")
```

`references/schema.md`（enum/對照卡，觸發後才載入）：
```
matches(folder, name, tournament, round, player_a, player_b, year, is_practice)
rallies(match_folder, rally_id, set_no, score_a, score_b, start_frame, end_frame, has_video, video_filename)
shots(match_folder, set_no, rally, ball_round, player /*A|B*/, server, type /*球種*/,
      aroundhead, backhand, hit_area, landing_area, lose_reason, win_reason,
      getpoint_player /*A|B*/, roundscore_a, roundscore_b, ...)

球種(type)：放小球,挑球,擋小球,殺球,點扣,發短球,推球,切球,過度切球,勾球,
           長球,發長球,平球,撲球,後場抽平球,防守回抽,防守回挑,未知球種
lose_reason：出界,對手落地致勝,未過網,掛網,落點判斷失誤
win_reason ：對手出界,落地致勝,對手未過網,對手掛網,對手落點判斷失誤
player/getpoint_player：A / B（姓名見 matches.player_a/player_b）
rally_id：set_scoreA_scoreB（如 1_05_04），對應 rally_video 檔名；查片段務必 has_video=1。
```

#### 3.3.3 為什麼這樣分
- **存取走 MCP**：`query`/`list_tables`/`describe_table` 是 typed 工具 → **確定路由、可稽核**，harness 直接看到工具名（§7）。
- **skill 當 playbook**：enum、範例、has_video 規則等領域知識漸進揭露，省 context、模組化（未來 charts/tactic-clips 同模式）。
- **不需要 exec**：DB 不再靠 CLI；skill 無腳本要跑。**即使 skill 沒被觸發，agent 仍可直接呼叫 badminton-db MCP 工具**（工具恆在）→ 比純 skill 方案穩健。

#### 3.3.4 注意事項
- `query` 僅單句 SELECT + `mode=ro`；`describe_table` 對表名做白名單正則。
- skill discovery 路徑（workspace `skills/` vs `~/.nanobot/skills/`）需依 nanobot 版本確認，見 §8。

#### 3.3.5 選項
- **typed-only（更嚴格）**：拿掉 `query`，只留 `list_matches(player?)`、`shot_stats(match, group_by)`、`find_rallies(match, type, has_video)` 等預設 typed 工具，完全不讓 agent 寫 SQL（最 deterministic，但統計彈性低、要先設計工具）。
- **hybrid**：typed 工具涵蓋常見題 + 保留 `query` 當 fallback。

---

### 3.4 reels（remote MCP + `badminton-reels` skill playbook）

reels MCP 是 **remote 既有服務（不改）**；另配一個本地 **`badminton-reels` skill** 當 playbook，與 `badminton-db` 對稱。

連線：見 `reels_mcp_usage.md`（remote HTTP，CF Access service token）。工具契約（摘自 `REELS_MCP_HANDOFF.md`）：

| 工具 | 輸入 | 輸出 |
|------|------|------|
| `generate_reel` | `match_name` (+ `style/duration_target_sec/focus_player/shot_types/sets/rally_ids/max_highlights/narrative_emphasis/voice_id`) | `{job_id, state}` |
| `get_reel_status` | `job_id` | `{state, stage, total_stages, message, error}` |
| `get_reel_result` | `job_id` | `{ready, video_url, selected_rally_ids, duration_sec, quality_score, style, script_summary}` |

`state ∈ {queued, running, succeeded, failed}`。

**非同步互動模式**（封裝在 `badminton-reels` skill playbook，見 §3.4.1）：
1. `generate_reel(...)` → 拿到 `job_id`，立即回覆使用者「影片生成中（約數分鐘）」。
2. 每隔一段時間 `get_reel_status(job_id)`，直到 `succeeded`/`failed`。
3. 成功 → `get_reel_result(job_id)` 取 `video_url` 呈現；失敗 → 回報 `error`。

**影片播放**：✅ 已確認 `video_url` **可直接於瀏覽器播放**（不需 service token）。因此 Agent 拿到 `video_url` 後，直接以連結/`<video>` 內嵌回給使用者即可，**不需要後端代理或簽章 URL**。

#### 3.4.1 `badminton-reels` skill（playbook）
不改 reels MCP；只新增本地 skill 把「非同步編排 + 慣例」漸進揭露。

```
${BADMINTONGPT_HOME}/skills/badminton-reels/
└── SKILL.md
```

`SKILL.md`：
```markdown
---
name: badminton-reels
description: 生成比賽精華短影音。當使用者要「做一支精華/highlight 影片」時，依本 playbook
  呼叫 badminton-reels MCP 工具（非同步，約數分鐘）。
---

# 流程（非同步）
1. generate_reel(match_name, style?, ...) → {job_id, state}；立即回覆使用者「生成中（約數分鐘）」。
2. 每隔一段時間 get_reel_status(job_id)，直到 state=succeeded / failed。
3. succeeded → get_reel_result(job_id) 取 video_url，直接內嵌/連結；failed → 回報 error。

# 慣例
- match_name 一律傳 matches.name（去 .mp4 的資料夾名；可先用 badminton-db 查/確認名稱）。
- video_url 可直接於瀏覽器播放，無需額外處理。
- 可選參數：style / duration_target_sec / focus_player / shot_types / sets / rally_ids /
  max_highlights / narrative_emphasis / voice_id（見上方契約表）。
```

> reels 工具是 typed MCP（確定路由）；skill 只補「怎麼編排這三個工具」。即使 skill 沒被觸發，agent 仍能直接呼叫 MCP 工具。

---

### 3.5 Web Search
開 `tools.web.enable=true` 即可，預設 `duckduckgo`（免金鑰）。需更高品質可換 `tavily`/`brave`（加 `apiKey`）。用於：選手最新排名、近況、賽事新聞等 DB 沒有的資訊。

### 3.6 Web UI
- 啟用 `channels.websocket {enabled:true, port:8765}`，以 `nanobot gateway` 啟動，瀏覽器開 `http://127.0.0.1:8765`。
- 先用內建 UI 驗證「對話 + 工具呼叫」；影片以 `video_url` 連結/內嵌呈現（依 §3.4 整合決策）。

---

## 4. 關鍵資料流（Sequence）

**Flow A — 統計查詢（text-to-SQL）**
```
User → Agent: 「Axelsen 用殺球得了幾分？」
Agent: (參考 badminton-db skill playbook：enum/A-B/範例)
Agent → badminton-db MCP: query("SELECT COUNT(*) ... WHERE type='殺球' AND player='A' AND win_reason<>''")
MCP → Agent: {"rows":[{"n":10}], "row_count":1}
Agent → User: 「殺球致勝 10 分。」(可附 SQL)
```

**Flow B — 戰術片段**
```
User → Agent: 「找這場 Lee 放小球的回合片段」
Agent → badminton-db MCP: query("SELECT DISTINCT rally_id, video_filename FROM rallies r JOIN shots s …
              WHERE s.type='放小球' AND s.player='B' AND r.has_video=1")
MCP → Agent: rows(有影片者)
Agent → User: 列出回合 + 片段（提醒：標註多但實際有檔者少）
```

**Flow C — 生成精華影片（非同步，跨 MCP）**
```
User → Agent: 「做一支這場精華」
Agent → reels.generate_reel(match_name, style=…) → {job_id, queued}
Agent → User: 「生成中…」
loop: Agent → reels.get_reel_status(job_id) → running/…/succeeded
Agent → reels.get_reel_result(job_id) → {video_url}
Agent → User: 影片連結/內嵌
```

**Flow D — 外部資訊**
```
User → Agent: 「Axelsen 最近世界排名？」
Agent → web.search(...) → web.fetch(...) → Agent → User（附來源）
```

---

## 5. 安全與部署
- **reels MCP**：經 Cloudflare Tunnel + Access service token（憑證放 env，不入庫）。
- **DB（badminton-db MCP）**：`query` 僅單句 SELECT + `mode=ro`；Agent 永遠無法寫入。自有容器、streamable-HTTP **只開在 compose 內網**（`badminton-db:8801`，不對 host 發佈、不進 tunnel）。
- **secrets**：全用 `${ENV}` 注入（OpenAI key、CF Access token）；以 systemd `EnvironmentFile=` 或 direnv 載入。
- **部署形態**：每個 MCP 各一個容器——`gateway`（nanobot + 內嵌 stdio `util`）、`badminton-db`（HTTP，掛載唯讀 `badminton.db`）、`cloudflared`；reels 為 remote。skill playbook 仍隨 gateway。
- 註：DB 改走 MCP 後**不再需要 exec**（少一個攻擊面）。

---

## 6. 實作步驟（how to write it，建議順序）

1. **DB ingestion**（§3.2）
   - 寫 `mcps/badminton-db/ingest.py`，解析用 vendored `ingest_lib/`（不依賴 badminton-reels；只需 `HF_TOKEN`）。
   - 範圍：`matches`=全 32 場目錄（不下載）、`rallies`/`shots`=本地 1 場。
   - 產出 `badminton.db`；用 `mcps/badminton-db/scripts/ground_truth.py` 的查詢核對數字（殺球致勝=10、出界=50、挑球 116/86…）。
2. **`badminton-db` MCP + skill playbook**（§3.3）
   - 寫 `mcps/badminton-db/server.py`（FastMCP streamable-http，`:8801/mcp` + `/healthz`：`list_tables`/`describe_table`/`query` SELECT-only）；設 `BADMINTON_DB`，本機手測（`MCP_TRANSPORT=stdio .venv/bin/python mcps/badminton-db/scripts/test_db_mcp.py`）。
   - 建 `skills/badminton-db/`：`SKILL.md` + `references/schema.md`（playbook，無腳本）。
3. **nanobot 設定**（§3.1）
   - 填 `~/.nanobot/config.json`（providers、websocket、tools.web、頂層 mcpServers：`badminton-db` 本地 stdio + `badminton-reels` remote）。
   - 確認兩支 MCP 的工具都列得出來、nanobot 能 discover 到 `badminton-db` skill。
   - 載入 env，`nanobot gateway`，確認 WebUI 起得來、web.search 可用。
4. **System prompt（精簡路由）**（§3.1.3）
   - 只寫人設 + 路由提示（DB→badminton-db MCP/skill、影片→reels、外部→web）；schema/enum 在 skill。
   - 用 Flow A/B 幾個問題手測：確認 DB 問題會呼叫 `query` 並寫對 SQL。
5. **reels 整合 + skill playbook**（§3.4 / §3.4.1）
   - 建 `skills/badminton-reels/SKILL.md`（playbook：非同步編排 + 慣例）。
   - 跑一次 Flow C（generate→status→result）；確認 `video_url` 可直接於瀏覽器播放。
6. **驗收 harness**（§7）
   - 寫 `eval/run_eval.py` 跑 9 題，比對工具呼叫與 ground truth。
7. **文件**：更新 README（啟動方式、env、ingest 指令）。

---

## 7. 測試與驗收（Success Metric）

沿用 `TASK.md` 的 9 題題庫（已含 ground truth）。harness 需檢查兩件事：**(1) 呼叫的工具是否符合預期**、**(2) 回應內容是否正確**。

#### 7.1 預期工具對照（節錄，完整見 TASK.md）
| # | 問題 | 預期工具 | Ground truth |
|---|------|---------|--------------|
| 1 | Axelsen 有哪些比賽 | badminton-db `query`(matches) | 6 場 |
| 2 | 殺球得幾分 | badminton-db `query`(shots) | 10 |
| 3 | 最常見失分原因 | badminton-db `query`(shots) | 出界 50 |
| 4 | 挑球次數比較 | badminton-db `query`(shots) | A116 / B86 |
| 5 | 三局比分 | badminton-db `query` | 19–21,21–11,23–21 |
| 6 | 放小球片段 | badminton-db `query`(rallies has_video) | 183 次標註，僅 8 檔 |
| 7 | 做 Axelsen vs Lee 這場精華 | reels.generate_reel→status→result | 產出可播放 video_url |
| 8 | 世界排名走勢 | web.search | 外部 |
| 9 | 年份/等級 | badminton-db `query`(matches) | 全 2022；27+5 |

> Q1/Q9 依賴 `matches` 已填滿全 32 場目錄（見 §3.2.2）；Q2–Q6 為本地那 1 場的逐拍資料。

#### 7.2 harness 設計（`eval/run_eval.py`）
- **驅動**：透過 nanobot websocket channel（`ws://127.0.0.1:8765`）逐題送出 prompt，收事件流。
- **抓工具呼叫**：開 `channels.sendToolHints=true`，從事件流解析「呼叫了哪個工具/MCP」；判斷是否命中「預期工具」。
  - 註：DB 題會呈現為 **badminton-db MCP 的 `query`**（typed 工具，確定路由、易比對）；reels 題看 `generate_reel` 等。比 exec/CLI 方案更容易抓。
- **驗答案**：對 SQL 題，另外直接跑對應 SQL 取 ground truth，比對 Agent 回答中的關鍵數字；reels 題檢查最終有 `video_url`；web 題檢查有呼叫 search。
- **輸出**：每題 `tool_match: pass/fail`、`answer_match: pass/fail`，總結通過率。

```python
# 骨架（事件協定需依實際 nanobot WS 格式調整）
CASES = [
  {"q": "資料庫裡有哪些 Axelsen 的比賽？", "expect_tool": "query",   # badminton-db MCP
   "check": lambda ans: "6" in ans or ans.count("AXELSEN") >= 6},
  {"q": "做一支 Axelsen vs Lee 這場的精華", "expect_tool": "generate_reel",
   "check": lambda ans: "http" in ans},   # 可播放 video_url
  # …其餘 7 題
]
# for c in CASES: send(c["q"]); ev = collect(); assert c["expect_tool"] in tools(ev); assert c["check"](final_text(ev))
```

> ⚠️ nanobot WS 事件格式需先實測確認（哪個欄位帶 tool 名稱）。若 WS 解析困難，退路：用 `nanobot agent` headless 跑單題、解析 stdout/log 的 tool hint。

---

## 8. 已確認的決策（前述問題已拍板）
1. ✅ **mcpServers 格式**：頂層 `mcpServers` + `type:http`（reels_mcp_usage.md 已實測可連，§3.1.1）。
2. ✅ **影片播放**：`video_url` 可在瀏覽器直接播放，直接內嵌/連結（§3.4）。
3. ✅ **LLM 預設**：OpenAI（deep/fast 皆 OpenAI；仍可切換，§3.1.1）。
4. ✅ **DB 範圍**：`matches`=全 32 場目錄、`rallies`/`shots`=本地 1 場（§3.2.2）。
5. ✅ **存取走 MCP、行為走 skill playbook（每能力各一）**：
   - DB＝本地 `badminton-db` MCP（`query`/`list_tables`/`describe_table`，SELECT-only）+ `badminton-db` skill（§3.3）；**不再用 exec**。
   - reels＝remote `badminton-reels` MCP + `badminton-reels` skill（非同步編排/慣例，§3.4.1）。
   - 細節（schema/enum、reels 編排）都從 system prompt 搬進各自 skill。

## 已實作並驗證（nanobot v0.2.1，2026-06-06）
實作後對若干「待實測」項的**實際結論**（與本文上方範例若有出入，以下為準）：
- **mcpServers 位置**：實際在 **`tools.mcpServers`**（非頂層）。遠端用 `type:"streamableHttp"` + `url` + `headers`；本地用 `type:"stdio"` + `command/args/env`。
- **skill 探索路徑**：**`~/.nanobot/workspace/skills/`**（已用 symlink 指向本專案 `skills/`）。
- **system prompt 位置**：寫在 **`~/.nanobot/workspace/SOUL.md`**（無 `systemPrompt` 設定鍵）；路由提示 + DB 速查規則放這裡。
- **model 設定**：`agents.defaults.model="gpt-5.1"`（**bare 名稱**，不要 `openai/` 前綴）、`provider="openai"`、`providers.openai.apiKey="${OPENAI_API_KEY}"`（nanobot 支援 `${VAR}`）。
- **WS / WebUI**：`channels.websocket{enabled:true,port:8765,websocketRequiresToken:false}`；`nanobot gateway` 後 WebUI 在 `ws://127.0.0.1:8765`（health 在 :18790）。
- **驗收驅動**：用 headless `nanobot agent -m` 解析 `↳` 工具提示（`sendToolHints:true`）即可，未走 WS。
- **重要 schema 修正**：`rallies`/`shots` 的 join key 改為 **`match_name`（= `matches.name`，不含 .mp4）**；原本含 .mp4 會讓 Agent 以可讀名 scope 查詢時得 0 筆。
- **結果**：`mcps/badminton-db/scripts/verify_db.py` 23/23；9 題 e2e 工具路由 8/8、答案 8/8（DB/web），reels `generate_reel` 路由正常並回 `job_id`。
- **每支 MCP 各自為政（容器化重構，已驗證）**：本 repo 自有 MCP 搬到 `mcps/`，各自獨立。
  - `badminton-db`＝**獨立容器**（`mcps/badminton-db/Dockerfile`，映像 `badmintongpt-db:0.1.0`，
    compose service `badminton-db`），改以 **streamable-HTTP** 對 compose 內網提供
    `http://badminton-db:8801/mcp`（無 auth、永不對外）＋ `GET /healthz`；nanobot config 用
    `{"type":"streamableHttp","url":"http://badminton-db:8801/mcp","enabledTools":[...]}` 連它。設
    `MCP_TRANSPORT=stdio` 才走 stdio（smoke test）。host/dev：`MCP_HOST=127.0.0.1 python mcps/badminton-db/server.py`。
  - `util`（sleep）＝**transport 不變**，仍是 **stdio**、由 gateway in-process 啟動（`{"type":"stdio",
    "command":"python3","args":["/app/mcps/util/server.py"],"enabledTools":["sleep"],"toolTimeout":70}`），
    **非獨立容器**。
  - `reels`＝**不變**，仍是 remote streamableHttp（`https://reels-mcp.nycu-adsl.cc/mcp`，
    `CF-Access-Client-Id/Secret` = `${REELS_CF_CLIENT_ID}/${REELS_CF_CLIENT_SECRET}`），本 repo 不容器化它。
  - **gateway 變純 host**：Dockerfile 不再 COPY `db_mcp/` / `ingest.py` / `scripts/`，改 COPY `mcps/util/`；
    gateway service 不再設 `BADMINTON_DB`，並 `depends_on: { badminton-db: { condition: service_healthy } }`；
    entrypoint 不再警告缺 DB 檔。cloudflared/tunnel 不變（只 tunnel gateway，db 純內網）。
  - **ingest reels-解耦**：`ingest.py` 不再注入 `$REELS_SRC` / `import badminton.*`，改用 vendored
    `mcps/badminton-db/ingest_lib/`（`RallySegment`/`ShotLabel` + `parse.extract_tournament_round` + 薄 HF
    `DataLoader`）；DB 建置只需 `HF_TOKEN`。`REELS_SRC`/`REELS_SRC_HOST` 已自 `.env.example`、compose ingest
    移除。一次性建置 `docker compose --profile ingest run --rm ingest`（跑 `badmintongpt-db` 映像）。
  - compose services 現為：`gateway`、`badminton-db`、`cloudflared`、`ingest`(profile)。
  - **驗證**：`depends_on` 健康序啟動 OK；gateway log 出現 `MCP server 'badminton-db': connected`（HTTP）、
    `util` connected（stdio）；HTTP 上 `list_tables`/`query` 正常、`DELETE` 被拒；`verify_db` 23/23、
    parity OK、解耦 ingest Axelsen vs Lee = **1213 shots**（A=Viktor AXELSEN、B=LEE Zii Jia）。
  - `example-mcp-server/`＝**獨立 docs 交付物**（`REMOTE_MCP_SERVER_GUIDE.md` 的範例），**不搬入** `mcps/`；
    其 `server.py` 本就跑 streamable-http（env `MCP_HOST/MCP_PORT/PUBLIC_BASE_URL/OUTPUT_DIR`），容器化無需改 code。
```
