---
name: badminton-reels
description: >-
  生成比賽精華短影音。當使用者要「做一支精華 / highlight / 剪輯 影片」時，依本 playbook
  呼叫 badminton-reels MCP 工具（非同步，約數分鐘）。
---

# badminton-reels playbook

reels 是 remote MCP，三個工具走**非同步** job 模式：

## 流程
1. `generate_reel(match_name, style?, ...)` → 取得 `{job_id, state}`。
   立即告訴使用者「影片生成中（約數分鐘）」，不要空等。
2. 每隔一段時間 `get_reel_status(job_id)` → 直到 `state` 為 `succeeded` 或 `failed`。
3. `succeeded` → `get_reel_result(job_id)` 取 `video_url`，**直接以連結/內嵌**回給使用者
   （video_url 可在瀏覽器直接播放，不需額外處理）。
   `failed` → 把 `error` 訊息回報給使用者。

## 慣例
- `match_name` 一律傳 **`matches.name`**（去 .mp4 的資料夾名）。不確定正確名稱時，
  先用 badminton-db 查：`SELECT name FROM matches WHERE name LIKE '%關鍵字%'`。
- 可選參數（調整風格與內容）：
  `style`（humorous/professional/dramatic/educational/concise…）、
  `duration_target_sec`、`focus_player`、`shot_types`、`sets`、`rally_ids`、
  `max_highlights`、`narrative_emphasis`、`voice_id`。
- `state` 列舉：`queued / running / succeeded / failed`。

## 範例
```
generate_reel(match_name="Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals",
              style="dramatic", duration_target_sec=90)
→ {job_id: "...", state: "queued"}
get_reel_status(job_id) → {state: "running", stage: 3, ...}
get_reel_result(job_id) → {ready: true, video_url: "https://.../files/<id>.mp4", ...}
```
