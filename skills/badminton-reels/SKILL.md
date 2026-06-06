---
name: badminton-reels
description: >-
  生成比賽精華短影音。當使用者要「做一支精華 / highlight / 剪輯 影片」時，依本 playbook
  呼叫 badminton-reels MCP 工具（非同步，約數分鐘；用 cron 排程在完成時通知使用者）。
---

# badminton-reels playbook

reels 是 remote MCP：`generate_reel` / `get_reel_status` / `get_reel_result`，render 約數分鐘。
**不要在同一輪對話裡卡著輪詢等它好**——改用「啟動 → 立刻回覆 → cron 週期檢查 → 完成時通知」。

## 流程（非同步、不阻塞對話）
1. `generate_reel(match_name, style?, ...)` → 取得 `{job_id, state}`。
2. **立刻回覆使用者**：「影片生成中（約數分鐘），好了我會把連結傳給你。」（這一輪到此結束，不要等。）
3. 用 **`cron`** 工具排一個每 60 秒的自我檢查，完成/失敗時通知並自我移除：
   ```
   cron  action=add
         name="reel-<JOB_ID>"
         every_seconds=60
         deliver=false                # 例行檢查不打擾使用者
         message="""Reels job <JOB_ID> 檢查：
           呼叫 get_reel_status(job_id='<JOB_ID>')。
           - succeeded → 呼叫 get_reel_result，用 message 工具把 video_url 傳給使用者；
                          再 cron action=list 找到名為 'reel-<JOB_ID>' 的 job_id，cron action=remove 移除它。
           - failed    → 用 message 工具回報 error；再 cron remove 'reel-<JOB_ID>'。
           - queued/running → 什麼都不做，等下次觸發。"""
   ```
   （把 `<JOB_ID>` 換成 generate_reel 回傳的真實 job_id。）

> ⚠️ cron **觸發中的執行不能再 add cron**（只能 list / remove）——所以用「週期 job + 完成時自我 remove」，
> 不要在檢查裡重排。完成通知用 **`message` 工具**主動送給使用者（因為 `deliver=false`）。

## 慣例
- `match_name` 一律傳 **`matches.name`**（去 .mp4 的資料夾名）。不確定就先用 badminton-db 查：
  `SELECT name FROM matches WHERE name LIKE '%關鍵字%'`。
- 可選參數（調整風格與內容）：`style`（humorous/professional/dramatic/educational/concise…）、
  `duration_target_sec`、`focus_player`、`shot_types`、`sets`、`rally_ids`、`max_highlights`、
  `narrative_emphasis`、`voice_id`。
- `state` 列舉：`queued / running / succeeded / failed`。
- `video_url` 可在瀏覽器直接播放，不需額外處理。

## 範例
```
generate_reel(match_name="Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals",
              style="dramatic", duration_target_sec=90)
→ {job_id: "ax-lee-001", state: "queued"}

# 回覆使用者「生成中…」後，排 cron：
cron action=add name="reel-ax-lee-001" every_seconds=60 deliver=false
     message="Reels job ax-lee-001 檢查：get_reel_status(...); succeeded→get_reel_result 後 message 使用者
              video_url 並 remove 此 cron；failed→message error 並 remove；否則略過。"

# ~數分鐘後 cron 觸發時：
get_reel_status(job_id="ax-lee-001") → {state: "succeeded"}
get_reel_result(job_id="ax-lee-001") → {ready: true, video_url: "https://.../files/ax-lee-001.mp4"}
# → message 使用者影片連結，cron remove "reel-ax-lee-001"
```

## 同步備援（短任務或使用者要求等）
若使用者明確要求「就在這裡等結果」，可改成同一輪輪詢：`get_reel_status` → 直到 terminal → `get_reel_result`。
但預設用上面的 cron 非同步通知，避免長時間佔住對話。
