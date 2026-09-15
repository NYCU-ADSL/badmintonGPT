---
name: long-mcp-job
description: >-
  Generic waiting playbook for long-running MCP jobs. When any MCP tool returns an asynchronous job
  (such as {job_id, state: queued/running}, with get_*_status / get_*_result tools),
  follow this playbook to poll silently within the same turn until completion: check status
  immediately, then sleep (choose 10–60 seconds) and check again. The UI displays a progress bar
  automatically. Never use cron or output text during polling.
---

# long-mcp-job playbook (generic asynchronous job waiting)

Applies to **any** MCP server following the async-job contract, regardless of domain:

| Role | Tool naming convention | Return value |
|------|------------|------|
| Start | `start_X` / `generate_X` (job spec) | `{job_id, state}` |
| Check status | `get_X_status(job_id)` | `{state, stage?, total_stages?, message?, error?}` |
| Get result | `get_X_result(job_id)` | `{ready, url/…}` |

Fixed `state` values: `queued / running / succeeded / failed`.

## Procedure (poll to completion within the same turn)

1. Call the start tool → obtain `job_id`.
2. **Immediately call `get_X_status(job_id)` once—do not sleep first**
   (the first status call makes the UI progress bar appear immediately).
3. **Polling loop**, based on the latest `state`:
   - `succeeded` → exit the loop, call `get_X_result(job_id)`, and return the result (URL, etc.) to the user.
   - `failed` → exit the loop and report `error`.
   - `queued` / `running` → call **util's `sleep(seconds=N)`** → `get_X_status(job_id)` → repeat this step.
     **Choose N yourself (10–60 seconds)**: use shorter waits at startup / `queued` (10–15s to catch
     the first running stage promptly); use 20–40s during steady `running`; shorten again when
     `stage` approaches `total_stages` (near completion).
4. If still unfinished at the limit → tell the user it is "still running," include `job_id`, and ask them
   to check again later (then call `get_X_result(job_id)` directly).

## Strict rules

> 🚫 **Never use `cron` to wait for a job** (whether `every_seconds` or `at`). When cron fires, it reads
> the message to the user as a reminder (e.g. "Remember to poll job …") instead of actually polling;
> recurring jobs may also fail to stop. Both methods failed in testing—always use same-turn polling above.

> 🔇 **Do not output any text response during polling**—a text-only response immediately **ends the turn**
> and interrupts polling. The WebUI **automatically displays** progress from tool results (recognizing
> `stage`/`total_stages`). Run the loop silently to terminal and return results only in the final response.
> Do not use the `message` tool either (it is prohibited for the current conversation).

> ⚠️ Each `sleep` must be 10–60 seconds (adjust to progress). **Never** repeatedly call status
> without sleeping; this wastes tool calls.
> 🚷 **Call only one tool per response**—never call `get_*_status` and `sleep` **in parallel in the same response**
> (tool events are sent only after the entire batch completes, so sleep delays the progress update by 30 seconds).
> Correct rhythm: status (alone) → sleep (alone) → status (alone) → …
> 💡 If the user interjects while polling, respond briefly and then resume polling.

## Example (a render tool following the async-job contract)

```
start_render(width=640, height=360, frames=60) → {job_id: "3226bea9", state: "queued"}

get_render_status("3226bea9") → {state: "queued", stage: 0, ...}    # Check immediately so progress appears at once
sleep(seconds=10)                                                    # Just started → short
get_render_status("3226bea9") → {state: "running", stage: 2, total_stages: 5, ...}
sleep(seconds=30)                                                    # Steady progress → medium
get_render_status("3226bea9") → {state: "running", stage: 4, total_stages: 5, ...}
sleep(seconds=15)                                                    # Nearly done → shorter
get_render_status("3226bea9") → {state: "succeeded"}
get_render_result("3226bea9") → {ready: true, url: "https://.../files/3226bea9"}
# No text during polling (the UI displays progress automatically)
# → Final response (brief): Done: https://.../files/3226bea9
```
