---
name: badminton-video-retrieval
description: >-
  以自然語言檢索羽球影片片段。當使用者要「找 / 搜尋 / 檢索 某個畫面或片段的影片」（例如
  「找有大對角殺球的片段」「哪段影片是網前搓球得分」）時，依本 playbook 呼叫
  badminton-video-retrieval MCP（非同步檢索，數十秒～數分鐘）。等待流程依 long-mcp-job
  skill 在同一輪安靜輪詢到完成，再把結果回給使用者。
---

# badminton-video-retrieval playbook

remote MCP，對影片做語意檢索（Milvus 向量庫）：`start_video_retrieval` →
`get_video_retrieval_status` → `get_video_retrieval_result`（標準 async-job contract）。

## 等待流程 → 依 **long-mcp-job** skill
最小摘要（細節與鐵則見該 skill）：`start_video_retrieval` 拿到 `job_id` 後**立刻先查一次
`get_video_retrieval_status`（不要先 sleep）**，之後「`sleep`（秒數自行拿捏 10–60）→ 再查」
輪詢到 terminal；**一次回應只呼叫一個工具**（status 和 sleep 絕不並列呼叫，否則進度會被拖延
30 秒）；**期間不輸出任何文字、絕不用 cron、不用 message 工具**——進度條由 WebUI 自動顯示。
`succeeded` → `get_video_retrieval_result`，把結果回給使用者；`failed` → 回報 `error`。

## 慣例（video-retrieval 領域知識）
- **`query` 一律用英文**自然語言描述想找的畫面 / 戰術 / 球種（例如
  `"smash winner to the deep diagonal corner"`）。**使用者用中文（或其他語言）問時，先把想找的
  內容翻成英文再當 `query` 送**；描述越具體、命中越準。（回覆使用者仍用其語言，只有送給 MCP
  的 `query` 是英文。）
- `return_mode`：`"best"`（預設，回經驗證的最佳單一結果）或 `"all"`（回顯示的所有 top 結果）。
  使用者只要一段就用 `best`；要多個候選就用 `all`。
- 結果若含可播放的影片 URL，用 **markdown 圖片語法** `![片段](video_url)` 回覆（前面的 `!`
  不可省略——WebUI 會自動把 `.mp4` 連結轉成內嵌 `<video>` 播放器）；**不要**用裸 URL 或純連結
  `[片段](video_url)`，那不會播放。若結果是指向資料庫既有比賽的片段（match / rally 參照），可
  搭配 badminton-db 補充比賽脈絡。
- 輔助工具：`list_milvus_collections`（看有哪些 collection）、`get_service_health`（服務 / 模型
  是否就緒）——診斷或使用者問「支援哪些資料 / 有哪些片庫」時才用。
- 與其他工具的分工：**找 / 搜尋既有影片片段** → 本 skill；**生成一支新的精華剪輯** →
  badminton-reels；**逐拍統計 / 數據** → badminton-db。

## 範例
```
# 使用者問「找有大對角殺球的片段」→ 先把 query 翻成英文再送
start_video_retrieval(query="smash winner to the deep diagonal corner", return_mode="best")
→ {job_id: "vr-001", state: "queued"}
# 之後依 long-mcp-job 輪詢：立刻 get_video_retrieval_status → sleep(15) → 再查 → … → succeeded
get_video_retrieval_result("vr-001") → { …影片結果… }
# → 最終回覆（簡短）＋（若結果含 video_url）![片段](video_url)
```
