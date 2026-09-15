---
name: badminton-reels
description: >-
  Generate match highlight videos. When the user wants to make a highlight or edited video,
  follow this playbook to call badminton-reels MCP (asynchronous rendering, taking a few minutes).
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

## Conventions (reels domain knowledge)
- Always pass **`matches.name`** as `match_name` (the folder name without .mp4). If unsure, query badminton-db first:
  `SELECT name FROM matches WHERE name LIKE '%keyword%'`.
- Optional parameters (style and content): `style` (humorous/professional/dramatic/educational/concise…),
  `duration_target_sec`, `focus_player`, `shot_types`, `sets`, `rally_ids`, `max_highlights`,
  `narrative_emphasis`, `voice_id`, `enable_anchor`.
- `state` values: `queued / running / succeeded / failed`.
- `video_url` plays directly in the browser without additional processing.
- **Always use Markdown image syntax for highlights**: `![Highlights](video_url)` (the leading `!` is required)—
  the WebUI automatically turns .mp4 links into embedded `<video>` players. **Do not** use a bare URL or a plain link
  `[Highlights](video_url)`; that displays only a clickable link and does not play the video.
- `enable_anchor` controls the presenter avatar; it is enabled by default unless the user asks to disable it.

## Example
```
generate_reel(match_name="Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals",
              style="dramatic", duration_target_sec=90, enable_anchor=true)
→ {job_id: "ax-lee-001", state: "queued"}
# Then poll per long-mcp-job: immediately get_reel_status → sleep(30) → check again → … → succeeded
get_reel_result("ax-lee-001") → {ready: true, video_url: "https://.../files/ax-lee-001.mp4"}
# → Final response (brief): Your highlights are ready!
# ![Highlights](https://.../files/ax-lee-001.mp4)
```
