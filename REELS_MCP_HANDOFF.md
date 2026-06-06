# badminton-reels → MCP 改造交接書

> **給接手的 Claude**：本文件描述把 `../badminton-reels`（相對於 `badmintonGPT`，絕對路徑 `/mnt/ssd1/howchien/badminton-reels`）改造成一個 **remote MCP server**（對外開放網路連線），由 badmintonGPT 的 nanobot agent 以**遠端 URL** 連入。目標 3 個工具：`generate_reel`（粗粒度、非同步、回 `job_id`，**可調整 reel 風格與內容**）、`get_reel_status`、`get_reel_result`。
>
> **Remote 的兩個關鍵差異**（務必貫徹全文）：
> 1. **傳輸用 Streamable HTTP**（不是 stdio），server bind 到可對外的 host:port。
> 2. **回傳影片要用可下載 URL**，不是本機檔案路徑——遠端 client 拿不到本機路徑。server 需另開靜態檔路由提供 `.mp4` 下載。
>
> 先讀懂現況再動手；所有檔案路徑、函式、行為描述皆已對照實際程式碼。**不要破壞既有 CLI**（`uv run python -m badminton ...` 要能照舊運作）。

---

## 0. 現況速覽（已核對程式碼）

| 檔案 | 角色 | 關鍵點 |
|------|------|--------|
| `src/badminton/__main__.py` | CLI 入口 | `main()` 解析 `match_name` + `--style`（預設 humorous）+ `--list-matches`，呼叫 `Pipeline().run(match_name, style)` |
| `src/badminton/pipeline.py` | 一條龍 pipeline | `Pipeline.run(match_name, style)` 5 階段：load→analyze→G-E-RG→TTS→compose，**用 `print` 報進度**，回傳輸出 `Path`。常數 `MAX_VIDEO_DURATION=180.0` |
| `src/badminton/match_analyzer.py` | 精彩篩選 | `MatchAnalyzer.analyze(match)` **自動**評分挑 **≤8** 個 highlights，指派五段式角色（hook/buildup/turning_point/climax/ending）。目前**不吃任何篩選參數** |
| `src/badminton/agents/writer.py` | 寫稿 | `generate_script(analysis, style, ...)`；style 只是被塞進 user_msg 的 `## 風格: {style}`，system prompt 固定讀 `prompts/writer.md`（幽默風） |
| `src/badminton/agents/graph.py` | G-E-RG loop | `NarrationState` TypedDict 帶 `style`；`create_narration_graph()` 回 LangGraph |
| `src/badminton/config.py` | 設定 | `Config` 在 import 時讀 env（OpenAI key/model、Fish、HF、`output_dir` 等）。`get_config()` 有 `@lru_cache` |
| `src/badminton/models.py` | Pydantic models | `MatchData / MatchAnalysis / RallyHighlight / NarrativeScript / ...` |

**真實可用的篩選維度**（來自逐拍資料，已驗證）：
- `type`（球種）：放小球、挑球、擋小球、殺球、點扣、發短球、推球、切球、過度切球、勾球、長球、發長球、平球、撲球、後場抽平球、防守回抽、防守回挑、未知球種
- `win_reason`/`lose_reason`：出界、(對手)落地致勝、(對手)未過網、(對手)掛網、落點判斷失誤
- `player`/`getpoint_player`：`A`/`B`
- rally 識別碼 `set_scoreA_scoreB`（如 `1_05_04`），對應 `rally_video/*.mp4`（**注意：實際只有部分回合有影片檔**）

---

## 改造任務（依序）

### 任務 1 — 定義 `ReelSpec` / `ReelResult`（新 model）
在 `src/badminton/models.py` 新增兩個 Pydantic model，作為「風格 + 內容」的單一輸入與結構化輸出。

```python
class ReelSpec(BaseModel):
    match_name: str
    # 風格
    style: str = "humorous"                  # preset 名稱或自由字串（見任務 3）
    duration_target_sec: int = 90            # 目標時長，clamp 到 [30, 180]
    # 內容控制（皆可選；None = 不限制）
    focus_player: str | None = None          # "A"/"B" 或選手姓名子字串；偏重此人得分/主控的回合
    shot_types: list[str] | None = None      # 偏好含這些球種的回合，例：["殺球","撲球"]
    sets: list[int] | None = None            # 只取指定局，例：[3]
    rally_ids: list[str] | None = None       # 明確指定回合（給定時略過自動篩選）
    max_highlights: int = 8                  # 1..12
    narrative_emphasis: str | None = None    # 例："逆轉"、"長多拍"、"進攻戰術"，注入寫稿
    only_with_video: bool = True             # 只挑 rally_video/ 真的有檔的回合
    voice_id: str | None = None              # 覆寫 Fish voice

class ReelResult(BaseModel):
    video_path: str                          # server 本機路徑（內部用，不回給遠端 client）
    video_url: str = ""                      # 對外可下載 URL（remote client 用，見任務 7/8）
    match_name: str
    selected_rally_ids: list[str]
    duration_sec: float
    quality_score: float
    style: str
    script_summary: str                      # 各段字幕串接或前 N 字
```

驗收：model 可被 import、`duration_target_sec`/`max_highlights` 有範圍 clamp（用 `model_validator`）。

---

### 任務 2 — `MatchAnalyzer` 支援內容篩選
改 `MatchAnalyzer.analyze` 接受可選 `spec: ReelSpec | None`，在現有評分流程上加篩選/加權，**不改既有預設行為**（`spec=None` 時行為與現在完全相同）。

需要動的點（`match_analyzer.py`）：
1. `analyze(self, match, spec=None)`：
   - 若 `spec.rally_ids` 有值 → 直接依該清單挑 segment（仍跑 `_describe_key_moments`、指派五段式角色），略過自動 top-N。
   - 否則在 `scored_rallies` 排序後、`_select_highlights` 前先**過濾**：
     - `spec.sets` → 只留 `seg.set_num in sets`
     - `spec.only_with_video` → 只留 `seg.video_path` 存在（需確保 analyzer 拿得到影片存在資訊，見下）
     - `spec.shot_types` → 對含這些球種的回合**加權**（在 `_score_excitement` 加 bonus 或排序前乘權重），而非硬性刪除，避免挑不滿。
     - `spec.focus_player` → 對「該球員在此回合得分 / 主控」的回合加權。
   - `spec.max_highlights` → 取代 `_select_highlights` 內寫死的 `8`（兩處 `>= 8` / `< 8` 改成參數）。
2. `only_with_video` 需要知道哪些 rally 有影片：
   - 簡單做法：在 analyzer 用 `match.rally_video_dir` 掃 `*.mp4` 得到存在集合；或在 `DataLoader.load_metadata` 時就把存在與否標到 `RallySegment.video_path`。擇一，註明選擇。

驗收：給 `spec.sets=[3]` 只會選到第 3 局回合；給 `spec.rally_ids=[...]` 完全照單；`spec=None` 輸出與改造前一致（可用同一場比較 highlight 集合）。

---

### 任務 3 — 風格（style）做成可擴充 preset + 自由字串
目前 style 只是字串塞進 user_msg，system prompt 永遠是幽默風。改成：

1. 新增 `prompts/styles/` 目錄，每個 preset 一個片段檔，例如：
   - `humorous.md`（把現有 `prompts/writer.md` 的「風格要求」段落搬過來）
   - `professional.md`（專業球評、術語精準、客觀）
   - `dramatic.md`（戲劇張力、懸念）
   - `educational.md`（適合教練/選手，解說戰術與技術重點）
   - `concise.md`（精簡快節奏）
2. `prompts/writer.md` 拆成「**共用骨架**」（輸出格式、Fish emotion tags、五段式結構、字數/節奏限制）＋ 風格段落由 preset 注入。
3. 改 `agents/writer.py` `generate_script`：
   - 新增參數 `emphasis: str | None = None`（來自 `ReelSpec.narrative_emphasis`）。
   - 載入 system prompt = 共用骨架 + 對應 style preset 內容；
     - 若 `style` 不是已知 preset，視為**自由風格指示**，直接當作風格段落注入（保留彈性）。
   - 把 `duration_target_sec`、`emphasis` 一併寫進 user_msg，讓模型對齊目標時長與敘事重點。
4. `graph.py`：`NarrationState` 增加 `emphasis` 與 `duration_target_sec` 欄位並一路傳到 `writer_node` → `generate_script`。

驗收：`style="professional"` 與 `style="humorous"` 產出語氣明顯不同；未知 style 字串不報錯、被當自由指示。

---

### 任務 4 — pipeline 函式化 + 進度回呼
讓 pipeline 能被程式呼叫並回報階段，給非同步 job 用。

改 `pipeline.py`：
1. 新增 `Pipeline.generate(self, spec: ReelSpec, on_progress=None) -> ReelResult`：
   - 內部沿用現有 5 階段，但：
     - `analyzer.analyze(match, spec)`；
     - graph 初始 state 帶入 `spec.style` / `spec.narrative_emphasis` / `spec.duration_target_sec`；
     - 用 `spec.duration_target_sec`（clamp）取代寫死的 `MAX_VIDEO_DURATION` 做加速判斷（保留 180 為硬上限）；
     - `voice_id` 傳給 TTS（若有）。
   - 把每個 `print(...)` 換成 `self._emit(on_progress, stage, msg)`，`on_progress(stage:int, total:int, msg:str)`；同時仍可 print 給 CLI。
   - 回傳 `ReelResult`（蒐集 selected_rally_ids、最終 duration、quality_score、script_summary、output 路徑）。
2. 保留舊的 `run(match_name, style)`：改成薄包 → `self.generate(ReelSpec(match_name=match_name, style=style)).video_path` 回 `Path`，確保 CLI 不變。

驗收：`uv run python -m badminton "<match>"` 行為不變；`Pipeline().generate(ReelSpec(...))` 可程式取得 `ReelResult`。

---

### 任務 5 — 設定可注入（provider/keys/output 覆寫）
目前 `Config` 在 import 時鎖定 env、`get_config()` 被 `@lru_cache`。為了 MCP 能由呼叫端覆寫（對應 badmintonGPT「LLM provider 可配置」）：
1. 讓 `Config` 可接受覆寫（例如 `get_config(overrides: dict | None = None)`，或新增 `set_config_overrides()`）。最小改動：把 `output_dir`、`fish_voice_id`、`openai_model`、`openai_api_key` 變成可被覆寫。
2. 不強求這次就抽換 OpenAI provider；但把 writer/critic/audience 取得 client 的地方集中成一個 `get_llm_client()`，方便日後切 provider。**若時間有限，至少完成 output_dir 與 voice_id 覆寫**（job 需要各自輸出目錄）。

驗收：可在不改 `.env` 的情況下，於呼叫端指定 `output_dir`，輸出落到指定資料夾。

---

### 任務 6 — Job 管理（非同步）
新增 `src/badminton/jobs.py`，提供跨呼叫可查詢的 job 狀態。建議用「背景執行緒 + 落地 JSON 狀態檔」，避免 MCP 工具阻塞數分鐘。

```python
# 狀態檔：{output_dir}/jobs/{job_id}.json
class JobStatus(BaseModel):
    job_id: str
    state: str            # "queued" | "running" | "succeeded" | "failed"
    stage: int = 0        # 0..5
    total_stages: int = 5
    message: str = ""
    result: ReelResult | None = None
    error: str | None = None
    spec: ReelSpec
```

`JobStore` 需求：
- `create(spec) -> job_id`：產生 id（**不要用 `uuid4`/時間亂數依賴隨機性問題**，可用 `match_name + 遞增序號 + spec hash`），寫入 `queued` 狀態檔，啟動背景 thread。
- 背景 thread 跑 `Pipeline().generate(spec, on_progress=回呼)`，每階段更新狀態檔（`running`, stage/message）；成功寫 `succeeded` + `result`，例外寫 `failed` + `error`（traceback 摘要）。
- `get(job_id) -> JobStatus`：讀狀態檔；找不到回明確錯誤。

驗收：建立 job 後立即 `get` 應為 `queued/running`；數分鐘後變 `succeeded` 且 `result.video_path` 存在。

---

### 任務 7 — Remote MCP server（Streamable HTTP + 影片下載路由）
新增 `src/badminton/mcp_server.py`，用官方 **Python MCP SDK**（`mcp` 套件的 `FastMCP`）。在 `pyproject.toml` 加 `mcp` 依賴，並加 entry point（例如 `badminton-mcp = "badminton.mcp_server:main"`）。

**傳輸**：用 **Streamable HTTP**（非 stdio）。**對外開放採 Cloudflare Tunnel + Access（選定方案，見附錄 A）**，因此 server 只需綁 `127.0.0.1`，由 `cloudflared` 以 outbound 連線對外曝光；**不要**綁 `0.0.0.0`、也不用自己開 port / 弄 TLS。

```python
mcp = FastMCP(
    "badminton-reels",
    host=os.getenv("MCP_HOST", "127.0.0.1"),  # 只給 cloudflared 連，不直接對公網
    port=int(os.getenv("MCP_PORT", "8900")),
)
# 對外網址＝Cloudflare Tunnel 的 hostname（見附錄 A），用來組 video_url
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://reels-mcp.example.com")

def main():
    mcp.run(transport="streamable-http")     # MCP 端點預設掛在 /mcp
```

**影片下載路由**（remote client 無法用本機路徑，必須能 HTTP 取檔）：FastMCP 基於 Starlette，可用 `@mcp.custom_route` 加一個檔案路由，把 `{output_dir}/.../*.mp4` 對外提供：

```python
from starlette.responses import FileResponse, JSONResponse
from starlette.requests import Request

@mcp.custom_route("/files/{job_id}.mp4", methods=["GET"])
async def serve_reel(request: Request):
    job_id = request.path_params["job_id"]
    s = STORE.get(job_id)
    if not s or s.state != "succeeded" or not s.result:
        return JSONResponse({"error": "not ready"}, status_code=404)
    return FileResponse(s.result.video_path, media_type="video/mp4",
                        filename=f"{job_id}.mp4")

@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request):
    return JSONResponse({"ok": True})
```

`video_url` 由 `PUBLIC_BASE_URL` + `/files/{job_id}.mp4` 組成，於 job 成功時寫入 `ReelResult.video_url`。

工具（名稱、輸入、輸出固定如下，Agent 端會依此對接）：

```python
@mcp.tool()
def generate_reel(
    match_name: str,
    style: str = "humorous",
    duration_target_sec: int = 90,
    focus_player: str | None = None,
    shot_types: list[str] | None = None,
    sets: list[int] | None = None,
    rally_ids: list[str] | None = None,
    max_highlights: int = 8,
    narrative_emphasis: str | None = None,
    voice_id: str | None = None,
) -> dict:
    """建立精華影片生成 job（非同步）。回傳 job_id 與初始狀態。"""
    spec = ReelSpec(...上述參數...)
    job_id = STORE.create(spec)
    return {"job_id": job_id, "state": "queued"}

@mcp.tool()
def get_reel_status(job_id: str) -> dict:
    """查詢 job 狀態：state / stage / message / error。"""
    s = STORE.get(job_id)
    return {"job_id": s.job_id, "state": s.state, "stage": s.stage,
            "total_stages": s.total_stages, "message": s.message, "error": s.error}

@mcp.tool()
def get_reel_result(job_id: str) -> dict:
    """取得完成後的結果；未完成時回 state 並提示尚未就緒。"""
    s = STORE.get(job_id)
    if s.state != "succeeded":
        return {"job_id": s.job_id, "state": s.state, "ready": False,
                "message": s.message or s.error or "尚未完成"}
    r = s.result
    return {"job_id": s.job_id, "state": s.state, "ready": True,
            "video_url": r.video_url, "selected_rally_ids": r.selected_rally_ids,
            "duration_sec": r.duration_sec, "quality_score": r.quality_score,
            "style": r.style, "script_summary": r.script_summary}
            # 註：回 video_url（可下載），不要回本機 video_path
```

另建議加一個唯讀工具或 resource：`list_matches() -> list[str]`（包 `DataLoader.list_matches()`），方便 Agent 先查可用比賽。

驗收：
- server 監聽 `127.0.0.1:8900`，`GET /healthz` 回 200（本機）；
- 經 cloudflared 後，從**外部**用 MCP client（帶 Access service token，見附錄 A）連 `https://reels-mcp.example.com/mcp` 能列出 3 個工具；
- `generate_reel(match_name=...)` 回 `job_id`；
- 輪詢 `get_reel_status` 由 running→succeeded；
- `get_reel_result` 回 `video_url`，且該 URL（帶 Access service token）能被 `curl` 下載到 `.mp4`。

---

### 任務 8 — 存取控制與濫用保護
對外由 Cloudflare Access 把關（見附錄 A），所以 app 層只需做「縱深防禦 + 濫用保護」，不必自己實作對外驗證/TLS。

1. **驗證主責在 Cloudflare Access**（service token，附錄 A）。Access 會擋掉沒帶 token 的請求，origin 只收到通過的流量。
2. **（選用）origin 縱深防禦**：在 Starlette middleware 驗 Cloudflare 注入的 `Cf-Access-Jwt-Assertion`（用 team 的 `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs` 公鑰驗 JWT），或保留一個 app 層 `MCP_AUTH_TOKEN` 作第二道（`/healthz` 放行）。預設可先只靠 Access，把這層列為 TODO。
3. **濫用保護**：限制同時進行的 job 數（`MAX_CONCURRENT_JOBS`，超過回明確錯誤），避免被灌爆把機器吃滿。
4. **影片下載授權**：`/files/{job_id}.mp4` 與 `/mcp` 同一個 Cloudflare 主機名，受**同一條 Access 政策**保護，因此預設即「需 service token 才能下載」。⚠️ 但這也代表**瀏覽器(end user)無法直接播放**——播放方案見附錄 A「影片如何給瀏覽器看」。

新增環境變數彙整（寫進 `.env.example` 與 README）：
`MCP_HOST(=127.0.0.1), MCP_PORT, PUBLIC_BASE_URL(=tunnel 網域), MAX_CONCURRENT_JOBS`，以及選用的 `MCP_AUTH_TOKEN`。
（Cloudflare 的 tunnel 憑證與 Access service token 屬 Cloudflare 設定，不放在 app env，見附錄 A。）

驗收：未帶 service token 的外部請求被 Access 擋下；帶正確 service token 可用 `/mcp` 與下載 `video_url`。

---

## badmintonGPT（nanobot）端如何連這個 remote MCP
（此段給 badmintonGPT 設定者參考，非 badminton-reels 的改動）

nanobot 在 `~/.nanobot/config.json` 以 **remote / streamable-http** 方式註冊，URL 指向 Cloudflare Tunnel 網域，header 帶 **Cloudflare Access service token**：

```jsonc
{
  "mcpServers": {
    "badminton-reels": {
      "type": "http",                         // streamable-http remote
      "url": "https://reels-mcp.example.com/mcp",
      "headers": {
        "CF-Access-Client-Id": "${CF_ACCESS_CLIENT_ID}",
        "CF-Access-Client-Secret": "${CF_ACCESS_CLIENT_SECRET}"
      }
    }
  }
}
```

（實際鍵名以 nanobot 文件為準；重點是「remote URL + CF-Access service token headers」。）連上後 agent 即可呼叫 `generate_reel / get_reel_status / get_reel_result`；取得 `video_url` 後的播放方式見附錄 A。

---

## 介面契約（給 Agent / nanobot 端，務必穩定）

連線方式：**remote Streamable HTTP over Cloudflare Tunnel**，端點 `<PUBLIC_BASE_URL>/mcp`，需帶 Cloudflare Access service token（`CF-Access-Client-Id` / `CF-Access-Client-Secret`）。

| 工具 | 輸入（必填） | 輸入（可選） | 輸出重點 |
|------|------------|------------|---------|
| `generate_reel` | `match_name` | `style, duration_target_sec, focus_player, shot_types, sets, rally_ids, max_highlights, narrative_emphasis, voice_id` | `{job_id, state}` |
| `get_reel_status` | `job_id` | — | `{state, stage, total_stages, message, error}` |
| `get_reel_result` | `job_id` | — | `{ready, video_url, selected_rally_ids, duration_sec, quality_score, style, script_summary}` |

`state` 枚舉固定：`queued / running / succeeded / failed`。影片以 `video_url`（`<PUBLIC_BASE_URL>/files/{job_id}.mp4`）下載，不回本機路徑。

---

## 不要做 / 注意事項
- **不要**改壞既有 CLI 與 `prompts/writer.md` 既有產出品質（拆 prompt 時把幽默風完整搬進 `styles/humorous.md`）。
- **不要**在 job id 或任何邏輯依賴 `random`/`Date.now`（保持可重現）。
- 影片生成需 `ffmpeg`(libass) 與 Fish/OpenAI key；MCP server 啟動時若缺 key 應在 `get_reel_status` 的 `failed.error` 清楚回報，而非整個 crash。
- `only_with_video=True` 很重要：資料集逐拍標註很多，但 `rally_video/` 只有部分回合有檔，挑到沒有影片的回合會導致黑畫面 fallback。
- **remote：絕不要回本機 `video_path` 給工具呼叫端**，一律回 `video_url`；本機路徑只在 server 內部與 `/files` 路由使用。
- **對外不要綁 `0.0.0.0`、不要自己開 port**：綁 `127.0.0.1`，一律經 Cloudflare Tunnel（附錄 A）對外；驗證交給 Cloudflare Access service token。
- 改完更新 `../badminton-reels/README.md` 與 `CLAUDE.md`：新增 **remote MCP 啟動方式（含 cloudflared）**、環境變數（`MCP_HOST/MCP_PORT/PUBLIC_BASE_URL/MAX_CONCURRENT_JOBS`、選用 `MCP_AUTH_TOKEN`）、`ReelSpec` 參數、style preset 清單。

## 完成定義（DoD）
1. `uv run python -m badminton "<match>"` 行為不變。
2. `uv run badminton-mcp`（或等效）以 **Streamable HTTP** 啟動，監聽 `127.0.0.1:MCP_PORT`，本機 `GET /healthz` 回 200。
3. `cloudflared` 把 `https://reels-mcp.<你的網域>` 對外曝光；從**外部**用 remote MCP client（帶 Access service token）連 `/mcp` 可列出 3 個工具。
4. 一次端到端：`generate_reel` → 輪詢 `get_reel_status` → `get_reel_result` 取得 `video_url`，且該 URL（帶 service token）`curl` 得到 `.mp4`。
5. 未帶/錯誤 service token 的外部請求被 Cloudflare Access 擋下。
6. style preset 至少 3 種可用且語氣不同；`shot_types`/`sets`/`rally_ids`/`focus_player` 任一能實際改變被選回合。
7. README/CLAUDE.md 同步更新。
8. 部署：依附錄 A 完成 Cloudflare Tunnel + Access，外部帶 service token 可走完端到端。

---

## 附錄 A — 部署方案（選定）：Cloudflare Tunnel + Access Service Token

**為什麼選這個**：reels pipeline 是 Python + ffmpeg + 數分鐘長任務，且資料/影片/環境都在本機。用 Cloudflare Tunnel 把**本機**的 MCP 安全曝光，不必開 port、不必公網 IP、不必自管 TLS；用 Access **service token** 做 server-to-server（nanobot ↔ MCP）驗證。Workers 不適合跑這種重任務、Containers 要重打包+付 egress，故不選。

**前置需求**：一個已託管在 Cloudflare 的網域（zone）＋ Cloudflare Zero Trust（Access）啟用。

### A.1 安裝並建立 Tunnel（在跑 MCP 的那台機器）
```bash
# 1) 安裝 cloudflared（依平台），登入並建立 tunnel
cloudflared tunnel login
cloudflared tunnel create reels-mcp        # 產生 tunnel id 與憑證 json

# 2) 綁一個對外 hostname 到這個 tunnel
cloudflared tunnel route dns reels-mcp reels-mcp.example.com
```

`~/.cloudflared/config.yml`（把對外流量轉到本機 MCP 的 127.0.0.1:8900）：
```yaml
tunnel: <TUNNEL_ID>
credentials-file: /home/<user>/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: reels-mcp.example.com
    service: http://127.0.0.1:8900     # FastMCP 監聽位址；/mcp 與 /files 都走這
  - service: http_status:404
```

以服務常駐：
```bash
cloudflared service install      # 或 cloudflared tunnel run reels-mcp
```
這樣 `https://reels-mcp.example.com/mcp`、`/files/{job_id}.mp4`、`/healthz` 都會經 Cloudflare 邊緣轉到本機。

### A.2 用 Access Service Token 保護（server-to-server）
1. Zero Trust 後台 → **Access → Applications → Add → Self-hosted**，Application domain 設 `reels-mcp.example.com`（涵蓋所有路徑）。
2. **Access → Service Auth → Create Service Token**，取得 **Client ID** 與 **Client Secret**（Secret 只顯示一次，妥善保存）。
3. 該 application 加一條 **policy**：Action = **Service Auth**，Include = 剛建立的 service token。
   - 效果：只有帶正確 `CF-Access-Client-Id` / `CF-Access-Client-Secret` 標頭的請求能到 origin，其餘被邊緣擋下。
4. （建議）在 Tunnel 設定開「**Protect with Access**」，讓 cloudflared 也驗 token，雙重保險。

### A.3 nanobot（badmintonGPT）端
把 service token 放進 nanobot 環境變數，於 `~/.nanobot/config.json` 帶上 CF-Access 標頭（同前文「nanobot 端如何連」）：
```
CF_ACCESS_CLIENT_ID=<Client ID>
CF_ACCESS_CLIENT_SECRET=<Client Secret>
```
`PUBLIC_BASE_URL`（MCP server 端）設成 `https://reels-mcp.example.com`，讓 `video_url` 對得上 tunnel 網域。

### A.4 影片如何給瀏覽器看（重要）
`/files/*.mp4` 與 `/mcp` 在同一 hostname、同一條 Access 政策下 → **一般使用者的瀏覽器沒有 service token，無法直接播放**。三選一：
- **(建議) 由 nanobot 後端代理**：agent 取得 `video_url` 後，nanobot 後端帶 service token 下載，再從 web UI 自己的網域回放給瀏覽器。end user 完全不碰 tunnel/Access，最單純。
- **簽章 URL + bypass**：reels 端為 `/files` 產生帶簽章與短效期的 URL（query string token），並在 Access 對 `/files/*` 設一條「Bypass（含驗 app 簽章）」政策；`/mcp` 維持 service token。
- **另開公開子網域**：把成品影片發佈到一個無 Access 的下載網域（或 R2 公開/簽章連結）。最省事但等於影片半公開，注意版權。

> 本專案預設採**第一種（nanobot 後端代理）**：安全邊界乾淨、不必動 Access 政策、影片永遠在 token 後面。

### A.5 本機快速自測（不經 Cloudflare）
```bash
# 啟動 MCP（127.0.0.1:8900）後：
curl -s http://127.0.0.1:8900/healthz          # {"ok": true}
# 經 tunnel + service token 的外部測試：
curl -s https://reels-mcp.example.com/healthz \
  -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET"
```
