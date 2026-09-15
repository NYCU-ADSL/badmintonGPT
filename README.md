# BadmintonGPT

A badminton match agent built around **nanobot**. Users ask questions in the web UI, and the agent autonomously routes them to:

- **badminton-db MCP** (local match SQLite database; read-only `query`/`list_tables`/`describe_table`)
- **badminton-reels MCP** (remote; generates highlight videos)
- **badminton-video-retrieval MCP** (remote; retrieves existing video clips using natural language)
- **badminton-analyze MCP** (remote; advanced statistics / tactical analysis for individual matches)
- **web search** (external information absent from the DB)

Each capability has a **skill playbook** (behavior layer); MCP is the access layer. See [`docs/DESIGN.md`](./docs/DESIGN.md) for the full design and [`docs/TASK.md`](./docs/TASK.md) for requirements context. All documentation is in [`docs/`](./docs); only `README.md` and `CLAUDE.md` remain at the repo root.

## Architecture

This repo's own MCPs live in `mcps/`, each independent and separately deployable; reels remains remote.

```
Browser ── ws:8765 ── nanobot Agent ──┬─ tools.mcpServers.badminton-db (streamableHttp, SELECT-only) ── badminton-db:8801/mcp ── badminton.db
   (SOUL.md routing + skills playbook)├─ tools.mcpServers.util (stdio, sleep; in-process)
                                     ├─ tools.mcpServers.badminton-reels (remote streamableHttp + CF Access)
                                     ├─ tools.mcpServers.badminton-video-retrieval (remote streamableHttp + CF Access)
                                     ├─ tools.mcpServers.badminton-analyze (remote streamableHttp + Bearer)
                                     └─ tools.web (duckduckgo) + fetch
```

- **badminton-db**: our own MCP, now serving **streamable HTTP** at `/mcp` (port 8801) in its own container; reachable only on the compose network, without auth. Set `MCP_TRANSPORT=stdio` to use stdio instead (for smoke tests).
- **util**: sleep MCP, still **stdio**, launched in-process by the gateway (no separate container).
- **badminton-reels**: remains remote streamableHttp (`https://reels-mcp.nycu-adsl.cc/mcp` + CF Access headers); not packaged by this repo.
- **badminton-video-retrieval**: remote streamableHttp (`https://video-retrieval.nycu-cgvlab.org/mcp` + CF Access headers).
- **badminton-analyze**: remote streamableHttp (`https://coachai.cs.nycu.edu.tw/mcp`), **using a bearer token**
  (`${ANALYZE_MCP_TOKEN}`, not CF Access); matches are identified by the numeric `matches.analyze_match_id`.

## Prerequisites

- `uv`, Python 3.12, `ffmpeg` (used on the reels side; already available remotely)
- HuggingFace token (already in `~/.cache/huggingface/token`, used by `ingest.py` to list 32 HF matches;
  another 163 come from `todo0819/Data-old.zip`; see `scripts/extract_data_old.py` and `CLAUDE.md`)
- **OpenAI API key**: set `OPENAI_API_KEY=` in this project's `./.env` (required; no fallback to other projects)
- Cloudflare Access service tokens: **one pair per remote MCP**, named `<NAME>_CF_CLIENT_ID/SECRET` (e.g. `REELS_CF_CLIENT_ID/SECRET` for reels), stored in this project's `./.env`
  (exception: `badminton-analyze` uses the bearer token `ANALYZE_MCP_TOKEN`, also in `./.env`)

## Installation

```bash
# 1) Project venv (for ingest.py and db MCP)
uv sync                       # Create .venv and install mcp / huggingface_hub / pydantic / ...

# 2) nanobot
uv tool install nanobot-ai
nanobot onboard               # Create ~/.nanobot/{config.json, workspace/}

# 3) Environment variables
cp .env.example .env          # Fill in OPENAI_API_KEY and REELS_CF_CLIENT_ID/SECRET
```

## Build the database

The DB build includes its own parser (`mcps/badminton-db/ingest_lib/`), needs only a HuggingFace token, and no longer depends on badminton-reels source.

```bash
.venv/bin/python mcps/badminton-db/ingest.py                 # Produce data/badminton.db
.venv/bin/python mcps/badminton-db/scripts/verify_db.py      # Compare against ground truth (23 checks)
```

- `matches`: catalog of all 32 matches (27 official + 5 NYCU practice).
- `rallies`/`shots`: **all 27 official matches** (downloads annotation CSVs for each match from HF, not videos; practice clips have no shot-by-shot data).
- `has_video` comes from the HF `rally_video/` listing (many annotations, few rallies with actual videos).
- **Always filter by `match_name` for a specific match** (= `matches.name`, without .mp4), or you will sum all 27 matches.

## Configure nanobot

Adjustments already made by this repo to `~/.nanobot/config.json`:

- `agents.defaults.model="gpt-5.1"`, `provider="openai"`; `providers.openai.apiKey="${OPENAI_API_KEY}"`
- `channels.websocket.enabled=true` (port 8765, `websocketRequiresToken=false`), `channels.sendToolHints=true`
- `tools.mcpServers`: `badminton-db` (`streamableHttp`, `url` points to the local db HTTP server `http://127.0.0.1:8801/mcp`); `util` (stdio, `command` = `python`, `args` = `mcps/util/server.py`); `badminton-reels` (remote `streamableHttp` + CF Access headers)
- Routing and DB quick-reference rules live in `~/.nanobot/workspace/SOUL.md`

**Copy** skills into the nanobot workspace (progressive disclosure of playbooks). Use `cp`, not `ln -s`:
nanobot's `restrictToWorkspace` boundary resolves symlinks before checking containment. A symlinked
skill directory resolves to a real path outside the workspace, blocking the agent from reading `SKILL.md`
(`Path .../SKILL.md is outside allowed directory`). Copying keeps it within the boundary.
After editing `skills/*`, rerun this script and restart the gateway:

```bash
./scripts/sync_skills.sh   # cp -r skills/* → ~/.nanobot/workspace/skills/ (removes old symlinks first)
```

## Run

### Local host mode (development)

The db MCP is now a local HTTP server and must be started in the background first (util is still launched
in-process by the gateway; no manual start needed). In the host's `~/.nanobot/config.json`,
`badminton-db` points to `http://127.0.0.1:8801/mcp`.

```bash
source scripts/load_env.sh      # Export OPENAI_API_KEY / REELS_CF_* for ${VAR} resolution

# badminton-db MCP (HTTP, background) — serves http://127.0.0.1:8801/mcp and GET /healthz
BADMINTON_DB=$PWD/data/badminton.db MCP_HOST=127.0.0.1 .venv/bin/python mcps/badminton-db/server.py &

# Web UI
nanobot gateway                 # Open http://127.0.0.1:8765

# Or a single question (headless)
nanobot agent -m "Which Axelsen matches are in the database?"
```

> **Host vs container configuration**: the committed `nanobot/config.json` template uses **container**
> hosts/paths (`http://badminton-db:8801/mcp`, `/app/mcps/util/server.py` for stdio util).
> For host mode, change only two entries in `~/.nanobot/config.json`: `badminton-db.url` →
> `http://127.0.0.1:8801/mcp`; stdio `util.args` → the local absolute path to `mcps/util/server.py`.
> Everything else (model, websocket, reels) is the same in both modes.
>
> **Common host-mode issues**
>
> - Always use `.venv/bin/python` (Python 3.12 with `mcp`); system `python3` is 3.8 without `mcp`.
> - Start db MCP (`MCP_HOST=127.0.0.1 … server.py &`) before `nanobot gateway`, or the agent cannot reach the DB.
> - `nanobot gateway` is an in-session background process and dies when the session ends (public 502/530 errors); use Docker for persistent deployment.
> - See `CLAUDE.md` (gotchas / runtime facts) and `docs/DEPLOY.md` (Docker troubleshooting) for deeper troubleshooting and runtime details.

### Production deployment (Docker Compose + Cloudflare Tunnel)

A reproducible deployment at `badmintongpt.<zone>`: `docker compose up` starts three services:
`gateway` (including our forked WebUI built from `vendor/nanobot/` and embedded util stdio MCP),
`badminton-db` (our HTTP MCP, internal-only `:8801`), and the `cloudflared` tunnel.
A separate `ingest` profile builds the DB once. The gateway waits for the DB through
`depends_on: badminton-db (healthy)`; agent configuration and instructions are committed as templates.
See **`docs/DEPLOY.md`** for full steps, including one-time Cloudflare setup, DB building, and acceptance checks.

```bash
cp .env.example .env            # Fill in OPENAI_API_KEY / REELS_CF_* / TUNNEL_TOKEN
docker compose --profile ingest run --rm ingest   # Build ./data/badminton.db (requires only HF_TOKEN)
docker compose up -d --build
docker compose up -d --force-recreate gateway
```

## Acceptance checks (Success Metric)

Nine questions (ground truth in `docs/TASK.md`) check tool routing and responses:

```bash
.venv/bin/python eval/run_eval.py            # All 9 questions (Q7 starts a remote editing job)
.venv/bin/python eval/run_eval.py --skip-reels   # Skip Q7 (no remote render)
```

## Files

```
mcps/badminton-db/                 # Our badminton-db MCP (own container, HTTP)
  server.py                        #   FastMCP streamable-http MCP: list_tables/describe_table/query(SELECT-only), GET /healthz
  ingest.py                        #   HF + local CSV → badminton.db (includes parser; no badminton-reels import)
  ingest_lib/                      #   Vendored RallySegment/ShotLabel + parse + thin HF DataLoader (HF_TOKEN only)
  scripts/ground_truth.py          #   Ground-truth oracle (in-memory)
  scripts/verify_db.py             #   23 assertions against badminton.db
  scripts/test_db_mcp.py           #   Standalone db MCP smoke test (MCP_TRANSPORT=stdio)
  scripts/test_decouple_parity.py  #   Parsing parity against badminton-reels after decoupling
  Dockerfile / pyproject.toml / README.md
mcps/util/server.py        # util sleep MCP (stdio, launched in-process by gateway)
skills/badminton-db/       # SKILL.md + references/schema.md (DB playbook)
skills/badminton-reels/    # SKILL.md (reels asynchronous orchestration playbook)
eval/run_eval.py           # Nine-question acceptance harness
scripts/load_env.sh        # Export runtime environment variables
example-mcp-server/        # Example for docs/REMOTE_MCP_SERVER_GUIDE.md (standalone documentation deliverable, outside mcps/)
monitoring/gatus/          # Gatus monitoring + public status page (single container, YAML monitors; see docs/MONITORING.md)
docs/                      # All documentation (see below)
  DESIGN.md  TASK.md       #   Full design / requirements context
  DEPLOY.md                #   Docker Compose + Cloudflare deployment
  MONITORING.md            #   Gatus uptime monitoring + badmintongpt-status.<zone> public status page
  ADD_NEW_MCP.md           #   Adding MCPs (own-container HTTP / stdio / skill / tests)
  MCP_TEST.md              #   mcp_test usage
  REMOTE_MCP_SERVER_GUIDE.md  #   Remote MCP tutorial (published as a docs site)
  REELS_MCP_HANDOFF.md  reels_mcp_usage.md   #   reels refactoring specification / connection instructions
```

See **`docs/ADD_NEW_MCP.md`** for adding MCPs (own-container HTTP / stdio / skill playbook / tests).
See **`docs/REMOTE_MCP_SERVER_GUIDE.md`** for building remote MCPs for other subprojects; use **`docs/MCP_TEST.md`** to check any MCP server (`python -m mcp_test <url>`).

## Known issues

- `round`: `Semifinals` may be parsed as `Finals` (inherited from reels' `_extract_tournament_round`; "Finals" is a substring of "Semifinals"). This affects display only, not the nine questions.
- Adjust `model="gpt-5.1"` to a version available to your OpenAI account.
- Shot-by-shot data covers 27 official matches; the five NYCU practice clips have only `matches` catalog entries. Always filter by `match_name` for single-match statistics.
