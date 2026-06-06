# BadmintonGPT

## Goal
打造接有多個羽球相關 MCP 以及賽事 DB 的 Agent，當使用者(大眾、教練、選手)對 Agent 問問題時，可以使用 MCP 功能做回應，以及透過 DB 及 Web search 去找相關資料。

## 受眾
1. 大眾
2. 教練, 選手

## 痛點
目前沒辦法透過 GPT, Gemini, Claude 等搜尋到選手特定戰術的片段，以及沒辦法根據需求生成精華片段。另外，也沒有辦法透過語意查詢得到分析圖表。

## How to solve?
1. 使用 https://github.com/HKUDS/nanobot 作為 Agent
2. 串接 DB 以及 web search
3. 串接 MCP，提供模板
4. DB 以 https://huggingface.co/datasets/howard9199/Badminton/tree/main 為範例，MCP 先串接 ../badminton-reels, 但先不要直接做 badminton-reels 的 MCP, 先告訴我怎麼改 badminton-reels 才適合作為 Agent 的 MCP

## 最終產出
一個 web UI（直接使用 nanobot 內建 WebUI，ws channel `http://127.0.0.1:8765`）

## Success Metric
設定幾個問題，以及對應應該呼叫的項目，檢查呼叫項目以及回應是否符合預期

---

## 確認後的決策 (2026-06-05)

| 項目 | 決策 |
|------|------|
| 本階段產出 | **只做規劃 + badminton-reels 改造指南**，先不寫實際 code |
| DB 形式 | **只用 SQLite（關聯式）**；語意查詢交由 LLM 把自然語言轉成 SQL/篩選條件 |
| Web UI | **直接用 nanobot 內建 UI**（不另外自建前端） |
| LLM provider | **可配置/本地**，指南寫成可切換（nanobot 支援多 provider + fallback），不綁定特定家 |
| Reels 工具粒度 | **粗粒度 + 非同步 job**：單一 `generate_reel` 回傳 `job_id`，另有查狀態/取結果工具 |

### MCP 工具範圍（已確認）
本階段唯一要做成 MCP 的能力：
1. **生成精華影片**（包裝 badminton-reels pipeline，粗粒度 + 非同步 job）

**暫不做 MCP（後續再議）**：
- 生成分析圖表（charts）
- 語意找戰術片段（tactic-clips）

**不需要 MCP**：
- 查詢選手/比賽數據 → Agent 直接對 SQLite 下 SQL（text-to-SQL）。
- 語意找戰術片段 → 暫先由 Agent text-to-SQL 篩出對應 rally、回傳 DB 內的影片片段路徑（不另做 MCP）。
- 分析圖表 → 本階段先不納入（待 reels MCP 跑通後再評估）。

---

## 系統架構（規劃）

```
                         ┌────────────────────────────┐
   使用者 (web UI) ──────▶│   nanobot Agent (loop)      │
                         │  - text-to-SQL 查 DB        │
                         │  - 呼叫 MCP 工具            │
                         │  - web search              │
                         └──────┬───────────┬─────────┘
                                │           │
              ┌─────────────────┘           └──────────────────┐
              ▼                                                  ▼
   ┌─────────────────────┐      Cloudflare Tunnel    ┌──────────────────────┐
   │  SQLite 賽事 DB      │   + Access service token  │  reels MCP (remote)   │
   │ (HF dataset 灌入)    │     (https://.../mcp)     │  Streamable HTTP      │
   │  - 逐拍標註          │◀── 共用資料來源 ────────│  bind 127.0.0.1       │
   │  - rally / 比分      │                          │  generate/status/     │
   │  - 影片片段路徑      │                          │  result + /files mp4  │
   └─────────────────────┘                          │ (charts/tactic-clips  │
                                                     │  暫不做 MCP)          │
                                                     └──────────────────────┘
```

## 元件設計

### 1. nanobot Agent
- 設定檔 `~/.nanobot/config.json`：宣告 provider/model（可切換）、啟用 WebSocket channel、註冊 MCP servers。
- Agent 能力：
  - **text-to-SQL**：把「查選手/比賽數據」的自然語言轉成對 SQLite 的查詢（不走 MCP）。
  - **MCP 工具呼叫**：reels / charts / tactic-clips。
  - **web search**：補充 DB 沒有的背景資訊（選手近況、賽事新聞等）。

### 2. SQLite 賽事 DB
- 以 HF dataset `howard9199/Badminton` 為來源，寫一支 ingestion 把 CSV 灌進 SQLite。
- **實際資料量（已核對）**：32 個資料夾＝**27 場 2022 正式賽事 + 5 段 `NYCU_Other_practice` 練習片**（男/女單）。
- 規劃資料表（依實際 dataset 結構）：
  - `matches`（比賽名稱、賽事、輪次、選手 A/B；可由資料夾名解析）
  - `rallies`（來自 `RallySeg.csv`，欄位：`Score, UpCourt, DownCourt, Start, End, Comment`；Score 即 rally 識別碼）
  - `shots`（來自 `label/set{1,2,3}.csv`，**實際 32 欄**）：
    `rally, ball_round, time, frame_num, end_frame_num, roundscore_A, roundscore_B, player(A/B), server, type, aroundhead, backhand, hit_height, hit_area, hit_x, hit_y, landing_height, landing_area, landing_x, landing_y, lose_reason, win_reason, getpoint_player, flaw, player_location_area/x/y, opponent_location_area/x/y, db`
- rally 識別碼沿用比分字串格式 `set_scoreA_scoreB`（如 `1_05_04`），對應 `rally_video/` 影片檔。
- **實際欄位值（供 text-to-SQL 對照）**：
  - `type`（球種）：放小球、挑球、擋小球、殺球、點扣、發短球、推球、切球、過度切球、勾球、長球、發長球、平球、撲球、後場抽平球、防守回抽、防守回挑、未知球種
  - `lose_reason`：出界、對手落地致勝、未過網、掛網、落點判斷失誤
  - `win_reason`：對手出界、落地致勝、對手未過網、對手掛網、對手落點判斷失誤
  - `player` / `getpoint_player`：`A` / `B`（A/B 對應的選手姓名需由 `matches`/`RallySeg` 對照，例如 Axelsen vs Lee 該場 A=Viktor AXELSEN、B=LEE Zii Jia）
  - ⚠️ 注意：`rally_video/` 只含部分回合片段（該場僅 8 個），ingestion 需標記哪些 rally 真的有影片檔。

### 3. MCP servers（提供模板）
本階段只做 reels 一支，且為 **remote MCP server**（對外開放、nanobot 以遠端 URL 連入）：

- 傳輸：**Streamable HTTP**（非 stdio），端點 `<PUBLIC_BASE_URL>/mcp`。
- 對外方式：**Cloudflare Tunnel + Access service token**（選定方案）。MCP 綁 `127.0.0.1`，由 `cloudflared` 對外曝光成 `https://reels-mcp.<網域>`；nanobot 帶 `CF-Access-Client-Id/Secret` 連入。
- 影片回傳：**可下載 URL**（`<PUBLIC_BASE_URL>/files/{job_id}.mp4`），非本機路徑；瀏覽器播放預設由 nanobot 後端代理（影片始終在 token 後面）。

| MCP | 工具 | 輸入 | 輸出 |
|-----|------|------|------|
| reels | `generate_reel` | match_name + 風格/內容參數 | `{job_id, state}` |
| reels | `get_reel_status` | job_id | `{state, stage, message, error}` |
| reels | `get_reel_result` | job_id | `{ready, video_url, ...}` |

> ✅ **reels MCP 已完成並部署**（remote `https://reels-mcp.nycu-adsl.cc`，CF Access 保護）。連線方式見 `reels_mcp_usage.md`；改造規格見 `REELS_MCP_HANDOFF.md`。
> 整體系統詳細設計與實作步驟見 **`DESIGN.md`**。
> charts、tactic-clips 暫不做 MCP：tactic-clips 先由 Agent text-to-SQL 回傳片段路徑；charts 本階段不納入。

### 4. Web UI
- 直接啟用 nanobot 內建 WebUI，先驗證對話 + 工具呼叫流程；圖表/影片以連結或內嵌方式呈現。

---

## badminton-reels 改造方向（本階段重點，先給指南、不動 code）

現況：`uv run python -m badminton "<match>"` 一條龍 pipeline（DataLoader → MatchAnalyzer → LangGraph G-E-RG → Fish TTS → ffmpeg），需數分鐘、依賴 ffmpeg/TTS/外部 API。

改造原則（指南需展開細節）：
1. **粗粒度 + 非同步**：對外只暴露 `generate_reel`（回 `job_id`）+ `get_reel_status` + `get_reel_result`，避免長任務阻塞 MCP/Agent。
2. **把 pipeline 入口函式化**：將 `__main__` 的 CLI 流程抽成可程式呼叫的函式（吃參數、回傳結構化結果與輸出路徑），讓 MCP 薄薄包一層即可。
3. **job 管理**：背景執行 + 狀態persist（job 狀態、進度、輸出檔路徑、錯誤訊息）。
4. **設定可注入**：API key / provider / model / 輸出目錄改成可由呼叫端覆寫，不只讀 `.env`。
5. **資料來源對齊**：reels 與 DB 共用同一份 HF 資料/路徑慣例，避免重複下載與不一致。

> 註：本階段「先告訴怎麼改」，不直接實作 badminton-reels 的 MCP。

---

## 本階段交付物
1. 系統架構與元件設計說明（即本檔上半部）。
2. **badminton-reels 改造指南**文件：列出需要重構的函式/介面、job 模型、設定注入點、MCP wrapper 介面草案。
3. MCP server 模板規格（reels / charts / tactic-clips 的工具簽名與 I/O 約定）。
4. SQLite schema 草案 + ingestion 規劃。
5. Success Metric 測試題庫（見下）。

---

## Success Metric — 測試題庫（依實際資料設計）
題目皆對應實際存在的資料夾、球種值、得失分原因。針對每題定義「應呼叫的項目」與可驗證的預期答案來源，再檢查實際呼叫與回應是否符合。

> **標準答案（ground truth）已實跑算出**，腳本：`scripts/ground_truth.py`（stdlib only，建記憶體 SQLite，灌入本地那場逐拍資料 + 32 場資料夾清單）。逐拍類答案僅針對本地唯一完整下載的 Axelsen vs Lee 該場（共 1213 筆 shots）。

| # | 使用者問題 | 預期呼叫 | ✅ 標準答案（已實跑） |
|---|-----------|---------|----------------------|
| 1 | 「資料庫裡有哪些 Axelsen 的比賽？」 | text-to-SQL（`matches`） | **6 場**：vs GINTING（World Tour Finals）、vs GINTING（Indonesia Masters）、vs CHOU Tien Chen、vs MOMOTA、vs NARAOKA、vs LEE Zii Jia |
| 2 | 「這場 Axelsen 用『殺球』得了幾分？」 | text-to-SQL（`type='殺球'` 且 A 致勝） | **殺球致勝 10 分**（Axelsen 全場殺球 52 次） |
| 3 | 「這場最常見的失分原因？」 | text-to-SQL（group by `lose_reason`） | **出界 50**＞對手落地致勝 34＞未過網 21＞掛網 10＞落點判斷失誤 1 |
| 4 | 「比較兩位選手『挑球』使用次數」 | text-to-SQL（group by `player`, `type='挑球'`） | **Axelsen(A) 116、Lee(B) 86**（合計 202） |
| 5 | 「這場三局比分各是多少？」 | text-to-SQL（最終 roundscore） | **第1局 19–21、第2局 21–11、第3局 23–21**（Axelsen 2–1 勝；A=Axelsen） |
| 6 | 「找這場 Lee『放小球』的回合片段」 | text-to-SQL 篩 rally → 回傳有影片的路徑 | Lee 放小球共 **183 次**；但本地 `rally_video/` 只有 **8 個**檔（`1_12_13,1_17_17,1_19_20,2_01_00,2_10_08,2_18_10,3_08_10,3_22_21`），須回傳實際存在者 |
| 7 | 「做一支這場的精華短影音」 | MCP `reels.generate_reel`→`get_reel_status`→`get_reel_result` | 回傳 job_id，最終產出 .mp4 路徑（無 SQL 真值） |
| 8 | 「Axelsen 之後的世界排名走勢？」 | web search | DB 無此資訊，需外部搜尋（無 DB 真值） |
| 9 | 「資料庫都是哪一年、哪些等級？」 | text-to-SQL（`matches`） | **全為 2022**；**27 場正式賽事 + 5 段 NYCU 練習片**（共 32 個資料夾） |

驗證方式：記錄 Agent 實際呼叫的工具序列與最終回應，比對是否命中「預期呼叫」，且答案與上表 ground truth / 外部來源一致。
（重跑標準答案：`python3 scripts/ground_truth.py`）
