---
name: badminton-video-retrieval
description: >-
  Retrieve badminton video clips using natural language. When the user wants to find, search for,
  or retrieve a scene or clip (for example, "find clips with a deep cross-court smash" or
  "which clip shows a spinning net shot winner"), follow this playbook to call
  badminton-video-retrieval MCP (asynchronous retrieval, taking tens of seconds to a few minutes).
  Follow the long-mcp-job skill to poll silently within the same turn until completion,
  then return the results to the user.
---

# badminton-video-retrieval playbook

Remote MCP for semantic video retrieval (Milvus vector database): `start_video_retrieval` →
`get_video_retrieval_status` → `get_video_retrieval_result` (standard async-job contract).

## Waiting procedure → follow the **long-mcp-job** skill
Brief summary (see that skill for details and strict rules): after `start_video_retrieval` returns a `job_id`,
**immediately call `get_video_retrieval_status` once (do not sleep first)**, then repeat
"sleep (choose 10–60 seconds) → check again" until terminal; **call only one tool per response**
(never call status and sleep in parallel, or progress will be delayed by 30 seconds);
**output no text during polling, never use cron, and do not use the message tool**—the WebUI displays progress automatically.
`succeeded` → `get_video_retrieval_result`, return the results to the user; `failed` → report `error`.

## ⚠️ Strict video_url rules (pitfalls observed in testing)
The output of `get_video_retrieval_result` is **large (up to ~30 KB, mostly analysis)**. The system truncates it
to a preview plus a saved-file path (`Full output saved to: …/tool-results/....txt`).
**The preview almost always ends before `video_url` appears.** In that case:
1. **Use `read_file` to read the saved file first** and find `video_url` (the last field in each result).
2. **Copy `video_url` verbatim** into the response—it is a long base64 string; **do not change a single character**.
3. 🚫 **Never construct a URL yourself**: do not base64-encode a guessed path or infer a filename from
   `parent_id`/`match_name` (the server's path format differs from your guess, resulting in a 404 and
   "No video with supported format and MIME type found" in the player). Do not output placeholders
   such as `…/files/...` either. **If you cannot find `video_url`, say so; do not invent one.**
4. Quick self-check: the base64 in a real `video_url` **does not end with `=`**. If the URL you are about to
   paste contains `=`, you almost certainly constructed it yourself—go back and read the saved file.

## Conventions (video-retrieval domain knowledge)
- **Always write `query` in English**, describing the scene, tactic, or shot type in natural language
  (for example, `"smash winner to the deep diagonal corner"`). **If the user asks in Chinese or another language,
  translate what they want into English before sending it as `query`**; more specific descriptions yield more
  accurate matches. (Still reply to the user in their language; only the MCP `query` is in English.)
- `return_mode`: `"best"` (default) or `"top_k"` — the server rejects anything else (e.g. `"all"`).
  `best` → `best_result` (+ `top_results`); `top_k` → `results` (+ `count`), up to 5 hits.
  Use `best` for a single clip and `top_k` for multiple candidates.
- Each hit carries `match_name` (= `matches.name`), `set_number` and `rally_number` (the N-th rally of that
  set, 1-based — **not** a reels/badminton-db `rally_id`; it equals `shots.rally`). Hits usually come from
  several different matches, and the search does **not** reliably filter by player or match names in `query`
  (it matches the described play). `winner_player` is a court side (`"Bottom-court Player"`), not a name.
- **To make a highlight from retrieved clips** (or any shot-type/scene highlight request): follow the
  **badminton-reels** skill, "Choosing rallies" — it converts these hits to `rally_ids` with the hit lookup below.
- `return_mode="top_k"` returns at most 5 hits. For an exhaustive ask ("all of X's smash clips"), say that
  retrieval shows the best few and offer a full list from badminton-db; do not verify hits one by one to fake completeness.

## Answering: the hits are the answer (badminton-db at most once)
- **Default: no badminton-db.** Answer from the result itself: `match_name` (readable as players + event),
  set/rally, `llm_reason` / `analysis.Narrative` for why it fits, and `video_url`. The retrieval server
  already ranked and LLM-verified the hits; do not re-verify the tactic shot by shot.
- **Use badminton-db only when** the user named a player/match (you must show which side they are and
  drop hits where they are not the one doing the play), or the hits feed `generate_reel`. Then run
  **exactly one** query covering **all** hits — it returns names, `rally_id`, `has_video`, the winner side
  and the shot sequence (`A:發短球 > B:放小球 > …`, `player` = hitter). Do not `describe_table`, do not
  improvise joins on scores, and do not query per hit:
  ```sql
  SELECT h.match_name, h.set_no, h.n AS rally_number, h.rally_id, h.has_video,
         m.player_a, m.player_b,
         (SELECT MAX(getpoint_player) FROM shots s
           WHERE s.match_name = h.match_name AND s.set_no = h.set_no AND s.rally = h.n) AS winner,
         (SELECT GROUP_CONCAT(player || ':' || type, ' > ')
            FROM (SELECT player, type FROM shots s
                   WHERE s.match_name = h.match_name AND s.set_no = h.set_no AND s.rally = h.n
                   ORDER BY ball_round)) AS shots
  FROM (SELECT match_name, set_no, rally_id, has_video,
               ROW_NUMBER() OVER (PARTITION BY match_name, set_no ORDER BY start_frame) AS n
        FROM rallies WHERE match_name IN ('<match A>', '<match B>')) h
  JOIN matches m ON m.name = h.match_name
  WHERE (h.match_name, h.set_no, h.n) IN (VALUES ('<match A>', 2, 23), ('<match B>', 3, 36))
  ```
  (`winner`/hitter `A`/`B` → `player_a`/`player_b`.) A hit with no row → present it from the hit alone,
  noting it could not be checked. If no hit features the named player, say so in one line and offer a
  badminton-db search instead of chaining more queries.
- Results are usually in each hit's `video_url` field, formatted as
  `https://video-retrieval.nycu-cgvlab.org/files/<long base64 string>`—**note that this URL does not end
  in .mp4** (the extension is encoded in base64). The server returns `Content-Type: video/mp4` and the video
  is playable, but the WebUI **uses the extension** to decide whether to embed a `<video>` player.
  Without an extension, it displays only a download link.
- **To embed video, always use Markdown image syntax with alt text ending in `.mp4`**:
  `![Clip.mp4](video_url)` (the leading `!` is required). The WebUI recognizes .mp4 in the alt text and
  embeds a `<video>` player, playable directly like highlight videos. **Do not** use `![Clip](video_url)`
  (no .mp4 in the alt text → only a download link, no playback), a bare URL, or a plain `[Clip](video_url)` link.
  (The alt text is only for WebUI recognition; it is not displayed as subtitles.)
- Auxiliary tools: `list_milvus_collections` (available collections), `get_service_health` (service/model readiness)—
  use only for diagnosis or questions about supported data or available video collections.
- Tool responsibilities: **find/search existing clips** → this skill; **generate a new highlight edit** →
  badminton-reels (for a shot-type/scene highlight it calls this skill first to pick the rallies);
  **shot-by-shot statistics/data** → badminton-db.

## Example
```
# User asks "Find clips with a deep cross-court smash" → translate the query into English first if needed
start_video_retrieval(query="smash winner to the deep diagonal corner", return_mode="best")
→ {job_id: "vr-001", state: "queued"}
# Then poll per long-mcp-job: immediately get_video_retrieval_status → sleep(15) → check again → … → succeeded
get_video_retrieval_result("vr-001") → { …, video_url: "https://video-retrieval.nycu-cgvlab.org/files/<base64>" }
# → Final response (brief) plus video (alt must end in .mp4 to embed the player):
# ![Clip.mp4](https://video-retrieval.nycu-cgvlab.org/files/<base64>)
```
