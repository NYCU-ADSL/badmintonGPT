---
name: long-mcp-job
description: >-
  通用「長時間 MCP 任務」等待 playbook。當任何 MCP 工具回傳非同步 job
  （如 {job_id, state: queued/running}，配套 get_*_status / get_*_result 工具）時，
  依本 playbook 在同一輪安靜輪詢到完成：立刻先查一次 status，之後 sleep（秒數自行
  拿捏 10–60）再查，UI 會自動顯示進度條。絕不使用 cron、輪詢期間不輸出文字。
---

# long-mcp-job playbook（通用非同步 job 等待）

適用於**任何**遵循 async-job contract 的 MCP server（不限特定領域）：

| 角色 | 工具命名慣例 | 回傳 |
|------|------------|------|
| 啟動 | `start_X` / `generate_X`（job spec） | `{job_id, state}` |
| 查狀態 | `get_X_status(job_id)` | `{state, stage?, total_stages?, message?, error?}` |
| 取結果 | `get_X_result(job_id)` | `{ready, url/…}` |

`state` 列舉固定：`queued / running / succeeded / failed`。

## 流程（同一輪輪詢到完成）
1. 呼叫啟動工具 → 取得 `job_id`。
2. **立刻先呼叫一次 `get_X_status(job_id)`——不要先 sleep**
   （第一次 status 會讓 UI 的進度條馬上出現）。
3. **輪詢迴圈** 依最近一次 status 的 `state`：
   - `succeeded` → 跳出迴圈，呼叫 `get_X_result(job_id)`，把結果（URL 等）給使用者。
   - `failed` → 跳出迴圈，回報 `error`。
   - `queued` / `running` → 呼叫 **util 的 `sleep(seconds=N)`** → 再 `get_X_status(job_id)` → 重複本步驟。
     **N 由你自行拿捏（10–60 秒）**：剛啟動/`queued` 用短一點（10–15s，盡快抓到第一個
     running stage）；穩定 `running` 用 20–40s；`stage` 接近 `total_stages`（快完成）再縮短。
4. 若達到上限仍未完成 → 告訴使用者「仍在進行中」並附上 `job_id`，請稍後再問（屆時直接
   `get_X_result(job_id)` 查）。

## 鐵則
> 🚫 **絕不要用 `cron` 來等 job**（不論 `every_seconds` 或 `at`）。cron 觸發時會把 message
> 當成「提醒」唸給使用者（例如「記得去輪詢 job …」），而不是真的去輪詢；週期 job 還會關不掉。
> 已實測兩種都失敗——一律用上面的同輪輪詢。

> 🔇 **輪詢期間不要輸出任何文字回覆**——純文字回應會直接**結束這一輪**、中斷輪詢。
> 進度條由 WebUI 從工具結果**自動顯示**（認 `stage`/`total_stages`），你只管安靜地把迴圈跑到
> terminal，最後一次回覆才給結果。也不要用 `message` 工具（它禁止對目前對話使用）。

> ⚠️ `sleep` 每次上限 60 秒、最短 10 秒（秒數依進度自行調整）。**絕不要**在沒有 `sleep` 的
> 情況下連續狂打 status（會空轉燒掉 tool 次數）。
> 🚷 **一次回應只呼叫一個工具**——`get_*_status` 和 `sleep` **絕不可在同一個回應裡並列呼叫**
> （工具事件要等整批跑完才會送出，並列會讓進度條被 sleep 拖延 30 秒才更新）。
> 正確節奏：status（單獨）→ sleep（單獨）→ status（單獨）→ …
> 💡 輪詢期間使用者若插話，先簡短回應再繼續輪詢。

## 範例（以 async-job contract 的 render 工具為例）
```
start_render(width=640, height=360, frames=60) → {job_id: "3226bea9", state: "queued"}

get_render_status("3226bea9") → {state: "queued", stage: 0, ...}    # 立刻先查，進度條馬上出現
sleep(seconds=10)                                                    # 剛啟動 → 短
get_render_status("3226bea9") → {state: "running", stage: 2, total_stages: 5, ...}
sleep(seconds=30)                                                    # 穩定運行 → 中
get_render_status("3226bea9") → {state: "running", stage: 4, total_stages: 5, ...}
sleep(seconds=15)                                                    # 快完成 → 縮短
get_render_status("3226bea9") → {state: "succeeded"}
get_render_result("3226bea9") → {ready: true, url: "https://.../files/3226bea9"}
# 輪詢全程不輸出文字（UI 自動顯示進度條）
# → 最終回覆（簡短）：好了：https://.../files/3226bea9
```
