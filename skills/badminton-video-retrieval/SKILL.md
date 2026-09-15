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
- `return_mode`: `"best"` (default, returns the best single verified result) or `"all"` (returns all displayed top results).
  Use `best` for a single clip and `all` for multiple candidates.
- Results are usually in each hit's `video_url` field, formatted as
  `https://video-retrieval.nycu-cgvlab.org/files/<long base64 string>`—**note that this URL does not end
  in .mp4** (the extension is encoded in base64). The server returns `Content-Type: video/mp4` and the video
  is playable, but the WebUI **uses the extension** to decide whether to embed a `<video>` player.
  Without an extension, it displays only a download link.
- **To embed video, always use Markdown image syntax with alt text ending in `.mp4`**:
  `![Clip.mp4](video_url)` (the leading `!` is required). The WebUI recognizes .mp4 in the alt text and
  embeds a `<video>` player, playable directly like highlight videos. **Do not** use `![Clip](video_url)`
  (no .mp4 in the alt text → only a download link, no playback), a bare URL, or a plain `[Clip](video_url)` link.
  (The alt text is only for WebUI recognition; it is not displayed as subtitles.) If a result refers to a
  clip from a match already in the database (match/rally references), use badminton-db to add match context.
- Auxiliary tools: `list_milvus_collections` (available collections), `get_service_health` (service/model readiness)—
  use only for diagnosis or questions about supported data or available video collections.
- Tool responsibilities: **find/search existing clips** → this skill; **generate a new highlight edit** →
  badminton-reels; **shot-by-shot statistics/data** → badminton-db.

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
