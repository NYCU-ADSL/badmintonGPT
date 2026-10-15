---
name: badminton-reels
description: >-
  Generate match highlight videos. When the user wants to make a highlight or edited video,
  follow this playbook to call badminton-reels MCP (asynchronous rendering, taking a few minutes).
  For a highlight about a shot type, scene or tactic, first find the rallies with video retrieval
  and pass them as rally_ids.
  Follow the long-mcp-job skill to poll silently within the same turn until completion,
  then return the video_url to the user.
---

# badminton-reels playbook

reels is a remote MCP: `generate_reel` → `get_reel_status` → `get_reel_result`; rendering takes a few minutes
(standard async-job contract).

## Waiting procedure → follow the **long-mcp-job** skill
Brief summary (see that skill for details and strict rules): after `generate_reel` returns a `job_id`,
**immediately call `get_reel_status` once (do not sleep first)**, then repeat "sleep (choose 10–60 seconds) → check again" until terminal;
**call only one tool per response (never call status and sleep in parallel, or progress will be delayed by 30 seconds)**;
**output no text during polling, never use cron, and do not use the message tool**—the WebUI displays progress automatically.
`succeeded` → `get_reel_result`, return `video_url` using **Markdown image syntax** `![Highlights](video_url)`
(the WebUI automatically embeds a `<video>` player; see conventions below); `failed` → report `error`.

## Choosing rallies: `rally_ids` (retrieve first, then generate)
- **Known rallies always go into `rally_ids`.** If earlier steps already pinned down specific rallies
  (video-retrieval hits, a badminton-db query, rallies the user named), pass them as `rally_ids` instead
  of letting reels auto-select. reels then uses exactly those rallies: `max_highlights`, `shot_types`,
  `sets`, `focus_player` are ignored, and IDs that match nothing are silently dropped.
- **Highlight about a shot type / scene / tactic** ("做一支殺球精華", "網前小球的精華", "make a highlight of
  deep cross-court smashes") → **first find the clips with video retrieval, then generate**:
  1. Follow the **badminton-video-retrieval** skill: `start_video_retrieval(query=<English description>,
     return_mode="top_k")`, poll per long-mcp-job, then `get_video_retrieval_result`. The result is large and
     usually truncated — `read_file` the saved output to get **every** hit's `match_name`, `set_number`,
     `rally_number`.
  2. **Convert hits to reels `rally_ids` with badminton-db.** A hit's `rally_number` is the N-th rally of that
     set (1-based), **not** a reels id; reels ids are `"<set>_<scoreA:02>_<scoreB:02>"` (e.g. `"2_16_07"`).
     Never pass `rally_number`, `parent_id` or the clip filename as a rally id. Map **all** hits with the
     **single "hit lookup" query** in the badminton-video-retrieval skill ("Answering" section) — it returns
     `rally_id`, `has_video`, player names and the shot sequence; do not run extra per-hit queries.
     Keep only rows with `has_video = 1` (an explicit rally without a clip is not filtered out by reels).
     A hit with no row is not in the rally catalog → drop it.
  3. **One match per reel.** `match_name` takes a single match, but retrieval hits usually span several
     matches. Generate for the match with the most usable hits (tie → the one holding the best-ranked hit),
     passing all of that match's `rally_ids`. In the final reply, name the other matches that also had hits
     and offer to make reels for them — do not start more jobs unasked (the server rejects more than 2
     concurrent jobs).
  4. `generate_reel(match_name=..., rally_ids=[...], <style etc. from the user>)` → wait per long-mcp-job.
     Mention in the final reply which rallies were used (`get_reel_result.selected_rally_ids`).
- **User named a specific match/player:** video retrieval does **not** understand player or match names
  (a query mentioning Axelsen still returns other matches). Keep only the hits from that match; if none
  remain, skip retrieval results and call `generate_reel` for that match with `shot_types=[...]`
  (badminton-db enum values, e.g. `["殺球"]`) instead of `rally_ids`.

## Conventions (reels domain knowledge)
- Always pass **`matches.name`** as `match_name` (the folder name without .mp4). If unsure, query badminton-db first:
  `SELECT name FROM matches WHERE name LIKE '%keyword%'`.
- Optional parameters (style and content): `style` (humorous/professional/dramatic/educational/concise…),
  `duration_target_sec`, `focus_player`, `shot_types`, `sets`, `rally_ids`, `max_highlights`,
  `narrative_emphasis`, `voice_id`, `enable_anchor`, `language`. For `rally_ids`, see "Choosing rallies" above.
- `state` values: `queued / running / succeeded / failed`.
- `video_url` plays directly in the browser without additional processing.
- **Always use Markdown image syntax for highlights**: `![Highlights](video_url)` (the leading `!` is required)—
  the WebUI automatically turns .mp4 links into embedded `<video>` players. **Do not** use a bare URL or a plain link
  `[Highlights](video_url)`; that displays only a clickable link and does not play the video.
- `enable_anchor` controls the presenter avatar; it is enabled by default unless the user asks to disable it.
- `language` (`zh-TW` | `en`) sets the narration script, TTS voice, and subtitle language. **Do not set it
  yourself**: the gateway fills it in automatically from the user's WebUI language (Chinese UI → `zh-TW`,
  any other UI language → `en`). The video service supports only these two narration languages. Pass it
  explicitly **only** when the user asks for a specific response or narration language (e.g. "narrate it in English")—an
  explicit value always wins. `get_reel_result` echoes the `language` used; mention it briefly in the final reply.

## Example
```
generate_reel(match_name="Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals",
              style="dramatic", duration_target_sec=90, enable_anchor=true)
→ {job_id: "ax-lee-001", state: "queued"}
# Then poll per long-mcp-job: immediately get_reel_status → sleep(30) → check again → … → succeeded
get_reel_result("ax-lee-001") → {ready: true, video_url: "https://.../files/ax-lee-001.mp4", language: "zh-TW", …}
# (no `language` was passed above—the gateway filled it from the user's UI language)
# → Final response (brief, for a Chinese UI): 精華影片已完成（繁體中文旁白）！
# ![Highlights](https://.../files/ax-lee-001.mp4)
```

## Example: shot-type highlight via video retrieval
```
# User: "幫我做一支後場殺球得分的精華"
start_video_retrieval(query="smash winner from the back court", return_mode="top_k") → {job_id: "vr-7"}
# poll per long-mcp-job → get_video_retrieval_result("vr-7") → read_file the saved output:
#   hits: (AN_Se_Young_TAI_Tzu_Ying_Korea_Open_2023_F, set 2, rally 33),
#         (Akane_YAMAGUCHI_CHEN_Yu_Fei_China_Open_2023_SF, set 2, rally 23), (…_China_Open_2023_SF, set 1, rally 37), …
query(<the video-retrieval skill's hit-lookup SQL with those hits>)   # one call for all hits
→ (…Korea_Open_2023_F, 2, 33, "2_20_13", 1), (…China_Open_2023_SF, 2, 23, "2_16_07", 1), (…China_Open_2023_SF, 1, 37, "1_18_19", 1)
# China Open SF has the most usable hits → one reel for it
generate_reel(match_name="Akane_YAMAGUCHI_CHEN_Yu_Fei_China_Open_2023_SF", rally_ids=["2_16_07", "1_18_19"])
# poll → get_reel_result → reply with the video, the rallies used, and offer a reel for Korea Open 2023 F too
```
