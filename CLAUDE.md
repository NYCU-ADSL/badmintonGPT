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
- **`skills/badminton-db/`, `skills/badminton-reels/`** — `SKILL.md` playbooks (enum values,
  query conventions, async-reel orchestration). Progressive-disclosure; they do NOT do the access.
- **web search** — nanobot's built-in `tools.web` (duckduckgo).

Config that drives all this lives **outside the repo** in `~/.nanobot/`:
- `~/.nanobot/config.json` — providers, websocket channel (:8765), `tools.mcpServers` (both MCPs).
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
cp .env.example .env                      # fill OPENAI_API_KEY + CF_ACCESS_CLIENT_ID/SECRET

# --- build / verify the DB ---
.venv/bin/python ingest.py                # all 27 official matches (downloads CSVs, not videos)
.venv/bin/python ingest.py --catalog-only # only the matches catalog
.venv/bin/python ingest.py --only <folder|name> --limit N   # subset (testing)
.venv/bin/python scripts/verify_db.py     # 23 assertions vs ground truth
.venv/bin/python scripts/ground_truth.py  # recompute the oracle numbers

# --- run the db MCP standalone (smoke test, no nanobot) ---
.venv/bin/python scripts/test_db_mcp.py

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

## When editing nanobot behavior

Routing rules and DB query conventions live in `~/.nanobot/workspace/SOUL.md` (always loaded);
deep schema/enum detail lives in the `skills/badminton-db/` playbook (loaded on demand). Skill
triggering is heuristic, so keep the must-know conventions in SOUL.md and the depth in the skill.
After changing the DB schema, update `ingest.py` DDL, `scripts/verify_db.py`,
`skills/badminton-db/references/schema.md`, and the SOUL.md conventions together.
