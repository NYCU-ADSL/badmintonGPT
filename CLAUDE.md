# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

BadmintonGPT is **not a Python application** — it is a set of scripts + config that wire up the
external **nanobot** agent framework (installed separately) to a local badminton SQLite DB and a
remote "reels" MCP. The runnable "app" is `nanobot gateway`; this repo provides the data, the
local MCP server, the skill playbooks, and the eval harness.

Architecture is **MCP (access layer) + skill playbooks (behavior layer)** — the 2026 hybrid:
- **`db_mcp/server.py`** — local **stdio** MCP `badminton-db` exposing `list_tables` /
  `describe_table` / `query` (single SELECT only, `mode=ro`). The agent's ONLY way to read the DB.
- **`badminton-reels`** — a **remote** MCP (already deployed at `reels-mcp.nycu-adsl.cc`, behind
  Cloudflare Access) that generates highlight videos. This repo does not implement it; see
  `REELS_MCP_HANDOFF.md` (how it was built) and `reels_mcp_usage.md` (how to connect).
- **`util_mcp/server.py`** — local **stdio** MCP `util` with a single `sleep(seconds≤60)` tool;
  exists solely to pace the async-job polling loop (registered with `toolTimeout: 70`).
- **`skills/badminton-db/`, `skills/badminton-reels/`, `skills/long-mcp-job/`** — `SKILL.md`
  playbooks (enum values, query conventions, and the **generic async-job wait recipe** — any MCP
  returning `{job_id, state}` is polled in-turn with util `sleep`; never cron, never mid-poll text).
  Progressive-disclosure; they do NOT do the access.
- **web search** — nanobot's built-in `tools.web` (duckduckgo).

Side deliverables for other sub-projects (self-contained, not needed to run the agent):
`REMOTE_MCP_SERVER_GUIDE.md` + `example-mcp-server/` = the onboarding tutorial, published as a
static site from `docs-site/` (MkDocs Material) by `.github/workflows/deploy-docs.yml` to Cloudflare
Pages at `badmintongpt-docs.nycu-adsl.cc`. `mcp_test/` is a read-only MCP conformance tester
(`python -m mcp_test <url> [--header "K: V"] [--stdio "cmd"]`, docs in `MCP_TEST.md`).

Config that drives all this lives **outside the repo** in `~/.nanobot/`:
- `~/.nanobot/config.json` — providers, websocket channel (:8765), `tools.mcpServers` (all three MCPs).
- `~/.nanobot/workspace/SOUL.md` — the agent persona + tool-routing rules + **DB query conventions**
  (this is the de-facto system prompt; there is no `systemPrompt` config key).
- `~/.nanobot/workspace/skills/` — where nanobot discovers skills; the repo's `skills/*` are
  **symlinked** here.

Requirements/spec: `TASK.md`. Full design + resolved decisions: `DESIGN.md` (§8 records the actual
nanobot v0.2.1 facts). Setup walkthrough: `README.md`.

## Data model & flow

HuggingFace dataset `howard9199/Badminton` → `ingest.py` → `data/badminton.db` (SQLite). Three
tables: `matches` (32 folders = 27 official + 5 NYCU practice), `rallies`, `shots`. `ingest.py`
**reuses `../badminton-reels`'s parsing** (`DataLoader._parse_rally_seg`, `_extract_tournament_round`,
the `ShotLabel` model) via `sys.path` injection of `$REELS_SRC` (default
`/mnt/ssd1/howchien/badminton-reels/src`). `shots`/`rallies` currently cover **all 27 official
matches** (~24k shots); practice clips have catalog metadata only.

Ground truth for verification lives in `scripts/ground_truth.py` (in-memory oracle) and is asserted
by `scripts/verify_db.py`. The 9-question success-metric bank is in `TASK.md` / `eval/run_eval.py`.

## Commands

```bash
# --- setup (once) ---
uv sync                                   # build .venv (py3.12: mcp, huggingface_hub, pydantic, websockets)
uv tool install nanobot-ai && nanobot onboard
ln -sfn "$PWD/skills/badminton-db"    ~/.nanobot/workspace/skills/badminton-db
ln -sfn "$PWD/skills/badminton-reels" ~/.nanobot/workspace/skills/badminton-reels
ln -sfn "$PWD/skills/long-mcp-job"    ~/.nanobot/workspace/skills/long-mcp-job
cp .env.example .env                      # fill OPENAI_API_KEY + CF_ACCESS_CLIENT_ID/SECRET

# --- build / verify the DB ---
.venv/bin/python ingest.py                # all 27 official matches (downloads CSVs, not videos)
.venv/bin/python ingest.py --catalog-only # only the matches catalog
.venv/bin/python ingest.py --only <folder|name> --limit N   # subset (testing)
.venv/bin/python scripts/verify_db.py     # 23 assertions vs ground truth
.venv/bin/python scripts/ground_truth.py  # recompute the oracle numbers

# --- run the db MCP standalone (smoke test, no nanobot) ---
.venv/bin/python scripts/test_db_mcp.py

# --- test any MCP server (conformance probe, used by other sub-projects too) ---
.venv/bin/python -m mcp_test https://reels-mcp.nycu-adsl.cc/mcp \
  --header "CF-Access-Client-Id: $REELS_CF_CLIENT_ID" \
  --header "CF-Access-Client-Secret: $REELS_CF_CLIENT_SECRET"

# --- rebuild/redeploy the patched WebUI (see "Patched WebUI" below) ---
./scripts/build_webui.sh && ./scripts/deploy_webui.sh

# --- run the agent ---
source scripts/load_env.sh                # exports OPENAI_API_KEY + CF_* from ./.env (no fallback)
nanobot gateway                           # WebUI at http://127.0.0.1:8765
nanobot agent -m "資料庫裡有哪些 Axelsen 的比賽？"   # one-shot headless

# --- success-metric eval (drives `nanobot agent`, parses ↳ tool hints) ---
.venv/bin/python eval/run_eval.py --skip-reels   # 8 cheap cases
.venv/bin/python eval/run_eval.py                # all 9 (Q7 triggers a real remote render)
.venv/bin/python eval/run_eval.py --only 4
```

There is no lint/test framework; verification = `verify_db.py` (data) + `run_eval.py` (e2e).

## Gotchas (these have all bitten — keep them in mind)

- **Always use `.venv/bin/python`** (py3.12 with `mcp`). System `python3` is 3.8 and lacks `mcp`.
  In `~/.nanobot/config.json`, the `badminton-db` MCP `command` must be the **absolute** path to
  this `.venv`'s python, not `"python"`.
- **`rallies`/`shots` join key is `match_name` = `matches.name` WITHOUT the `.mp4` suffix.**
  Scoping a per-shot query by `matches.folder` (which has `.mp4`) returns 0 rows. Since `shots`
  now holds 27 matches, **per-match questions MUST filter by `match_name`** or they sum across all.
- **A/B ↔ player name**: do NOT use `DataLoader._extract_players` (it returns the first rally's
  up/down court, which flips between games). `ingest.py:derive_ab` binds A = the player whose name
  appears first in the folder, matched case/underscore-insensitively. `matches.player_a/_b` are
  only filled for matches that have per-shot data.
- **Label CSVs have a few malformed rows.** `ingest.py` parses them row-tolerantly; do NOT switch
  to `DataLoader.load_metadata`/`_parse_label_csv` for labels — those are all-or-nothing and a
  single bad row drops the whole set (caused 3 matches to land with 0 shots before the fix).
- Build the full 32-folder catalog via `HfApi().list_repo_files`, NOT `DataLoader.list_matches()`
  (the latter filters out `NYCU_*`, breaking the practice-clip count).
- `has_video` comes from the HF `rally_video/` listing (videos are not downloaded); a labeled
  rally may legitimately lack a video, so clip queries should filter `has_video=1`.
- **Secrets**: `OPENAI_API_KEY` and `CF_ACCESS_*` are read ONLY from this repo's `.env`
  (`scripts/load_env.sh`, `eval/run_eval.py`) — no fallback to other projects. nanobot resolves
  them via `${VAR}` substitution at startup, so they must be exported before `nanobot gateway`.
- Model in config is the **bare** name `gpt-5.1` with `provider: "openai"` (not `"openai/gpt-5.1"`).

## nanobot v0.2.1 runtime facts (verified in source/logs — do not re-litigate)

- **cron is a reminder system, not a background-task runner.** Every user cron job fires wrapped in
  "Deliver this reminder to the user now…" (`cli/commands.py`), so the agent *relays* the message
  instead of executing it; recurring jobs also never self-delete. This is why the skills forbid cron
  for job-waiting — both the recurring and one-shot `at` variants failed in practice.
- **Start order: reels before gateway.** If the remote reels MCP is unreachable at gateway startup
  (502 from the tunnel because origin :8900 died), the whole gateway crashes (anyio cancel-scope
  bug). Always `curl 127.0.0.1:8900/healthz` first; restart reels with
  `cd /mnt/ssd1/howchien/badminton-reels && uv run badminton-mcp`.
- **A text-only assistant response ends the turn** (per-session serial; cross-session concurrent,
  gate=3). Hence: no mid-poll text output, and progress display belongs to the UI, not the model.
- **Tool events reach the WebUI only after the whole iteration's tool batch finishes** — hence the
  skill rule "one tool call per response" (batching `get_*_status` with `sleep` delays the progress
  bar by the sleep duration).
- gpt-5.1 (reasoning model) emits **no user-visible text alongside tool calls** — instructions to
  "narrate progress while polling" cannot work; don't try prompt-engineering around it.
- The gateway and reels server currently run as in-session background processes, **not systemd** —
  they die with the session (recurring 502/530s). Converting to systemd user services is the known fix.

## Patched WebUI (progress bar)

The served WebUI is a **patched rebuild**, not the stock dist: a generic `ToolProgress` card renders a
live progress bar for any tool whose result has numeric `stage`+`total_stages` (e.g. `get_reel_status`).
Source clone: `/mnt/ssd1/howchien/nanobot-webui` (HKUDS/nanobot @ v0.2.1 + `patches/webui-progress.patch`).
Rebuild with `scripts/build_webui.sh`, deploy with `scripts/deploy_webui.sh` (backs up the stock dist to
`dist.orig`, refuses to deploy onto a nanobot version ≠ 0.2.1). **`uv tool upgrade nanobot-ai` wipes the
deployed dist** — re-run deploy (and rebase the patch if the version changed). Do not upgrade casually.

## When editing nanobot behavior

Routing rules and DB query conventions live in `~/.nanobot/workspace/SOUL.md` (always loaded);
deep schema/enum detail lives in the `skills/badminton-db/` playbook (loaded on demand). Skill
triggering is heuristic, so keep the must-know conventions in SOUL.md and the depth in the skill.
After changing the DB schema, update `ingest.py` DDL, `scripts/verify_db.py`,
`skills/badminton-db/references/schema.md`, and the SOUL.md conventions together.
The async-job wait recipe is owned by `skills/long-mcp-job/` (SOUL rule 3 carries the one-line
summary; `skills/badminton-reels/` is domain knowledge only) — edit them together, then restart
the gateway (reels first; see runtime facts above) to pick changes up.
