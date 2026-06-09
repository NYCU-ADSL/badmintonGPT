---
name: badminton-reels
description: >-
  生成比賽精華短影音。當使用者要「做一支精華 / highlight / 剪輯 影片」時，依本 playbook
  呼叫 badminton-reels MCP（非同步 render，約數分鐘）。等待流程依 long-mcp-job skill
  在同一輪安靜輪詢到完成，再把 video_url 回給使用者。
---

# badminton-reels playbook

reels 是 remote MCP：`generate_reel` → `get_reel_status` → `get_reel_result`，render 約數分鐘
（標準 async-job contract）。

## 等待流程 → 依 **long-mcp-job** skill
最小摘要（細節與鐵則見該 skill）：`generate_reel` 拿到 `job_id` 後**立刻先查一次
`get_reel_status`（不要先 sleep）**，之後「`sleep`（秒數自行拿捏 10–60）→ 再查」輪詢到 terminal；
**一次回應只呼叫一個工具（status 和 sleep 絕不並列呼叫，否則進度會被拖延 30 秒）**；
**期間不輸出任何文字、絕不用 cron、不用 message 工具**——進度條由 WebUI 自動顯示。
`succeeded` → `get_reel_result`，把 `video_url` 以 **markdown 圖片語法** `![精華](video_url)` 回覆
（WebUI 會自動內嵌 `<video>` 播放器，見下方慣例）；`failed` → 回報 `error`。

## 慣例（reels 領域知識）
- `match_name` 一律傳 **`matches.name`**（去 .mp4 的資料夾名）。不確定就先用 badminton-db 查：
  `SELECT name FROM matches WHERE name LIKE '%關鍵字%'`。
- 可選參數（調整風格與內容）：`style`（humorous/professional/dramatic/educational/concise…）、
  `duration_target_sec`、`focus_player`、`shot_types`、`sets`、`rally_ids`、`max_highlights`、
  `narrative_emphasis`、`voice_id`、`enable_anchor`。
- `state` 列舉：`queued / running / succeeded / failed`。
- `video_url` 可在瀏覽器直接播放，不需額外處理。
- **回覆精華時務必用 markdown 圖片語法** `![精華](video_url)`（前面的 `!` 不可省略）——
  WebUI 會自動把 `.mp4` 連結轉成內嵌 `<video>` 播放器。**不要**用裸 URL 或純連結
  `[精華](video_url)`，那只會顯示成一條可點擊的連結、不會播放。
- `enable_anchor` 是主播頭像，預設為開啟，除非 user 要求關閉

## 範例
```
generate_reel(match_name="Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals",
              style="dramatic", duration_target_sec=90, enable_anchor=true)
→ {job_id: "ax-lee-001", state: "queued"}
# 之後依 long-mcp-job 輪詢：立刻 get_reel_status → sleep(30) → 再查 → … → succeeded
get_reel_result("ax-lee-001") → {ready: true, video_url: "https://.../files/ax-lee-001.mp4"}
# → 最終回覆（簡短）：你的精華好了！
# ![精華](https://.../files/ax-lee-001.mp4)
```
