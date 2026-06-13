# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

BadmintonGPT is **not a Python application** — it is a set of scripts + config that wire up the
external **nanobot** agent framework (installed separately) to a badminton SQLite DB (served by its
own MCP container) and a remote "reels" MCP. The runnable "app" is `nanobot gateway`; this repo
provides the data, the MCP servers (`mcps/`), the skill playbooks, and the eval harness.

Architecture is **MCP (access layer) + skill playbooks (behavior layer)** — the 2026 hybrid. This
repo's own MCPs live under `mcps/`, each self-contained:
- **`mcps/badminton-db/server.py`** — the `badminton-db` MCP exposing `list_tables` /
  `describe_table` / `query` (single SELECT only, `mode=ro`). The agent's ONLY way to read the DB.
  Served over **streamable-HTTP** (FastMCP `mcp.run(transport="streamable-http")`) at `/mcp` on port
  **8801**, in its **own** Docker container (`mcps/badminton-db/Dockerfile`, image
  `badmintongpt-db:0.1.0`, compose service `badminton-db`); also serves `GET /healthz`. nanobot
  reaches it at `http://badminton-db:8801/mcp` (no auth — internal compose network only, never
  host-published, never tunneled). Set env `MCP_TRANSPORT=stdio` to serve stdio instead (the smoke
  test does this). The dir also holds `ingest.py` (the DB build), `ingest_lib/` (vendored parsing —
  see below), `scripts/{ground_truth,verify_db,test_db_mcp,test_decouple_parity}.py`, a `Dockerfile`,
  `pyproject.toml`, and `README.md`.
- **`badminton-reels`** — a **remote** MCP (already deployed at `reels-mcp.nycu-adsl.cc`, behind
  Cloudflare Access) that generates highlight videos. This repo does not implement it and does not
  containerize it here (a Dockerfile for self-hosting is being added to the separate
  `badminton-reels` repo; this repo's config keeps pointing at the remote URL); see
  `docs/REELS_MCP_HANDOFF.md` (how it was built) and `docs/reels_mcp_usage.md` (how to connect).
- **`mcps/util/server.py`** — local **stdio** MCP `util` with a single `sleep(seconds≤60)` tool;
  exists solely to pace the async-job polling loop (registered with `toolTimeout: 70`). NOT its own
  container — the gateway launches it in-process over stdio.
- **`skills/badminton-db/`, `skills/badminton-reels/`, `skills/long-mcp-job/`** — `SKILL.md`
  playbooks (enum values, query conventions, and the **generic async-job wait recipe** — any MCP
  returning `{job_id, state}` is polled in-turn with util `sleep`; never cron, never mid-poll text).
  Progressive-disclosure; they do NOT do the access.
- **web search** — nanobot's built-in `tools.web` (duckduckgo).

Side deliverables for other sub-projects (self-contained, not needed to run the agent):
`docs/REMOTE_MCP_SERVER_GUIDE.md` + `example-mcp-server/` = the onboarding tutorial, published as a
static site from `docs-site/` (MkDocs Material) by `.github/workflows/deploy-docs.yml` to Cloudflare
Pages at `badmintongpt-docs.nycu-adsl.cc`. `mcp_test/` is a read-only MCP conformance tester
(`python -m mcp_test <url> [--header "K: V"] [--stdio "cmd"]`, docs in `docs/MCP_TEST.md`).

Config that drives all this is **committed in the repo** under `nanobot/` (the canonical templates)
and lands in `~/.nanobot/` at runtime — copied in host mode (config copied/pointed at, skills via
`scripts/sync_skills.sh`), installed by `docker/entrypoint.sh` in the Docker deploy:
- `nanobot/config.json` — providers, websocket channel (:8765), `tools.mcpServers` (all three MCPs):
  `badminton-db` = `{ "type": "streamableHttp", "url": "http://badminton-db:8801/mcp",
  "enabledTools": [...] }` (no auth); `util` = `{ "type": "stdio", "command": "python3",
  "args": ["/app/mcps/util/server.py"], "enabledTools": ["sleep"], "toolTimeout": 70 }`;
  `badminton-reels` = remote `streamableHttp` at `https://reels-mcp.nycu-adsl.cc/mcp` with
  `CF-Access-Client-Id`/`-Secret` headers (`${REELS_CF_CLIENT_ID}`/`${REELS_CF_CLIENT_SECRET}`).
  No secrets in the file (uses `${VAR}`); the committed copy uses **container paths/hosts**
  (`/app/...`, `http://badminton-db:8801`, websocket host `0.0.0.0`). The host-mode
  `~/.nanobot/config.json` instead points `badminton-db` at `http://127.0.0.1:8801/mcp` and uses
  absolute paths for the stdio `util` server.
- `nanobot/workspace/SOUL.md` — the agent persona + tool-routing rules + **DB query conventions**
  (the de-facto system prompt; there is no `systemPrompt` config key). `AGENTS.md` / `USER.md` /
  `HEARTBEAT.md` are the stock workspace templates.
- `~/.nanobot/workspace/skills/` — where nanobot discovers skills; the repo's `skills/*` are
  **copied** here (host mode `scripts/sync_skills.sh`, container via the entrypoint's `cp -r`).
  Do **NOT** symlink them: nanobot's `restrictToWorkspace` boundary resolves symlinks before the
  containment check (`security/workspace_policy.py:is_path_within` → `Path.resolve()`), so a
  symlinked skill dir resolves to its real path *outside* the workspace and the agent's `read_file`
  fails with `Path .../SKILL.md is outside allowed directory (... hard policy boundary ...)`.
  Copying keeps them in-bounds. Trade-off: editing `skills/*` needs a re-copy (re-run
  `scripts/sync_skills.sh`, or rebuild/restart the container) before nanobot sees the change.
- `vendor/nanobot/` — the **patched** nanobot source (HKUDS/nanobot v0.2.1 + `patches/webui-progress.patch`),
  vendored so the Docker image builds the progress-bar WebUI hermetically (see `vendor/README.md`).

Requirements/spec: `docs/TASK.md`. Full design + resolved decisions: `docs/DESIGN.md` (§8 records the actual
nanobot v0.2.1 facts). Setup walkthrough: `README.md`.

## Data model & flow

HuggingFace dataset `howard9199/Badminton` → `mcps/badminton-db/ingest.py` → `data/badminton.db`
(SQLite). Three tables: `matches` (32 folders = 27 official + 5 NYCU practice), `rallies`, `shots`.
`ingest.py` is now **decoupled from `../badminton-reels`** — it imports from the vendored
`mcps/badminton-db/ingest_lib/` (`RallySegment`/`ShotLabel` models, `parse.extract_tournament_round`,
a thin HF `DataLoader`) instead of injecting `$REELS_SRC` or importing `badminton.data_loader` /
`badminton.models`. The DB build therefore needs **only `HF_TOKEN`** (no `OPENAI`/`FISH`/reels).
`shots`/`rallies` currently cover **all 27 official matches** (~24k shots); practice clips have
catalog metadata only.

Ground truth for verification lives in `mcps/badminton-db/scripts/ground_truth.py` (in-memory oracle)
and is asserted by `mcps/badminton-db/scripts/verify_db.py`. `scripts/test_decouple_parity.py` (same
dir) checks
the vendored `ingest_lib/` parsing still matches the upstream reels parsing. The 9-question
success-metric bank is in `docs/TASK.md` / `eval/run_eval.py`.

## Commands

```bash
# --- setup (once) ---
uv sync                                   # build .venv (py3.12: mcp, huggingface_hub, pydantic, websockets)
uv tool install nanobot-ai && nanobot onboard
./scripts/sync_skills.sh                  # COPY skills/* → ~/.nanobot/workspace/skills/ (NOT symlink; see Gotchas)
cp .env.example .env                      # fill OPENAI_API_KEY + REELS_CF_CLIENT_ID/SECRET

# --- build / verify the DB (all paths under mcps/badminton-db/) ---
.venv/bin/python mcps/badminton-db/ingest.py                # all 27 official matches (CSVs, not videos; needs HF_TOKEN)
.venv/bin/python mcps/badminton-db/ingest.py --catalog-only # only the matches catalog
.venv/bin/python mcps/badminton-db/ingest.py --only <folder|name> --limit N   # subset (testing)
.venv/bin/python mcps/badminton-db/scripts/verify_db.py     # 23 assertions vs ground truth
.venv/bin/python mcps/badminton-db/scripts/ground_truth.py  # recompute the oracle numbers
.venv/bin/python mcps/badminton-db/scripts/test_decouple_parity.py  # vendored ingest_lib vs upstream reels parsing

# --- run the db MCP standalone ---
MCP_TRANSPORT=stdio .venv/bin/python mcps/badminton-db/scripts/test_db_mcp.py   # stdio smoke test, no nanobot
MCP_HOST=127.0.0.1 .venv/bin/python mcps/badminton-db/server.py                 # HTTP server at http://127.0.0.1:8801/mcp (host/dev mode)

# --- test any MCP server (conformance probe, used by other sub-projects too) ---
.venv/bin/python -m mcp_test https://reels-mcp.nycu-adsl.cc/mcp \
  --header "CF-Access-Client-Id: $REELS_CF_CLIENT_ID" \
  --header "CF-Access-Client-Secret: $REELS_CF_CLIENT_SECRET"

# --- rebuild/redeploy the patched WebUI (see "Patched WebUI" below) ---
./scripts/build_webui.sh && ./scripts/deploy_webui.sh

# --- run the agent (host/dev mode) ---
source scripts/load_env.sh                # exports OPENAI_API_KEY + CF_* from ./.env (no fallback)
MCP_HOST=127.0.0.1 .venv/bin/python mcps/badminton-db/server.py &   # db MCP over HTTP (host config points here)
nanobot gateway                           # WebUI at http://127.0.0.1:8765 (util stays in-process stdio)
nanobot agent -m "資料庫裡有哪些 Axelsen 的比賽？"   # one-shot headless

# --- reproducible deploy (Docker Compose + Cloudflare tunnel; see docs/DEPLOY.md) ---
docker compose --profile ingest run --rm ingest   # build ./data/badminton.db on badmintongpt-db image (needs only HF_TOKEN)
docker compose up -d --build                       # gateway (patched WebUI) + badminton-db + cloudflared

# --- success-metric eval (drives `nanobot agent`, parses ↳ tool hints) ---
.venv/bin/python eval/run_eval.py --skip-reels   # 8 cheap cases
.venv/bin/python eval/run_eval.py                # all 9 (Q7 triggers a real remote render)
.venv/bin/python eval/run_eval.py --only 4
```

There is no lint/test framework; verification = `verify_db.py` (data) + `run_eval.py` (e2e).

## Gotchas (these have all bitten — keep them in mind)

- **Always use `.venv/bin/python`** (py3.12 with `mcp`). System `python3` is 3.8 and lacks `mcp`.
  `badminton-db` is now reached over HTTP, so in `~/.nanobot/config.json` it is a `streamableHttp`
  **`url`** (`http://badminton-db:8801/mcp` in Docker, `http://127.0.0.1:8801/mcp` host-mode), NOT a
  `command`. Only the stdio `util` server still carries an absolute python path.
- **`rallies`/`shots` join key is `match_name` = `matches.name` WITHOUT the `.mp4` suffix.**
  Scoping a per-shot query by `matches.folder` (which has `.mp4`) returns 0 rows. Since `shots`
  now holds 27 matches, **per-match questions MUST filter by `match_name`** or they sum across all.
- **A/B ↔ player name**: do NOT reconstruct it from a rally's up/down court (it flips between games).
  `mcps/badminton-db/ingest.py:derive_ab` binds A = the player whose name appears first in the
  folder, matched case/underscore-insensitively. `matches.player_a/_b` are only filled for matches
  that have per-shot data. (Verified: decoupled ingest of the Axelsen–Lee match → 1213 shots,
  A = `Viktor AXELSEN`, B = `LEE Zii Jia`.)
- **Label CSVs have a few malformed rows.** `mcps/badminton-db/ingest.py` parses them
  row-tolerantly; do NOT switch to an all-or-nothing CSV loader, where a single bad row drops the
  whole set (caused 3 matches to land with 0 shots before the fix).
- Build the full 32-folder catalog via `HfApi().list_repo_files`, NOT a filtered `list_matches()`
  helper that drops `NYCU_*` (which would break the practice-clip count). The parsing now lives in
  the vendored `mcps/badminton-db/ingest_lib/` — there is no `badminton-reels` import.
- `has_video` comes from the HF `rally_video/` listing (videos are not downloaded); a labeled
  rally may legitimately lack a video, so clip queries should filter `has_video=1`.
- **Secrets**: `OPENAI_API_KEY` and the per-MCP `*_CF_CLIENT_ID/SECRET` (e.g. `REELS_CF_CLIENT_ID`)
  are read ONLY from this repo's `.env`
  (`scripts/load_env.sh`, `eval/run_eval.py`) — no fallback to other projects. nanobot resolves
  them via `${VAR}` substitution at startup, so they must be exported before `nanobot gateway`.
  `TTS_API_KEY` (WebUI message TTS) is **optional** and read straight from `os.environ` by the
  gateway's `/api/tts` proxy (NOT via `${VAR}`/config.json) — unset → the speaker button returns
  503. Server-side only; it never reaches the browser. See "Message TTS" below + `docs/MESSAGE_TTS.md`.
- Model in config is the **bare** name (not `"openai/gpt-5.1"`) with `provider: "openai"`. It is now
  env-driven: `nanobot/config.json` has `"model": "${NANOBOT_MODEL}"`, set via `.env`
  (`NANOBOT_MODEL=gpt-5.1`). nanobot **errors on an unset `${VAR}`**, so both modes provide a
  fallback: `scripts/load_env.sh` exports `NANOBOT_MODEL:-gpt-5.1` (host) and `docker-compose.yml`
  uses `${NANOBOT_MODEL:-gpt-5.1}` (Docker). The WebUI Settings panel reads config **unresolved**
  (so it wouldn't expand `${VAR}`); `patches/webui-model-from-env.patch` makes `settings_api.py`
  resolve the model for display (like `api_base`) and **not clobber** the `${NANOBOT_MODEL}` ref
  when the WebUI echoes the resolved value back on save. (Bootstrap/header already uses the resolved
  runtime model, so only Settings needed it.)
- **Skills must be COPIED into `~/.nanobot/workspace/skills/`, never symlinked.** With
  `restrictToWorkspace: true` (the deployed config), the read_file boundary check
  (`security/workspace_policy.py:is_path_within`) calls `Path.resolve()`, which **follows
  symlinks**. A symlinked skill dir therefore resolves to its real path *outside* the workspace
  (`/mnt/ssd1/.../skills/...` host, `/app/skills/...` Docker) and reading its `SKILL.md` fails with
  `Path .../skills/badminton-reels/SKILL.md is outside allowed directory ... (... hard policy
  boundary ...)` — this is exactly what breaks reel generation, since the agent loads the
  `badminton-reels` SKILL.md on demand. Fix: `scripts/sync_skills.sh` (host) / entrypoint `cp -r`
  (Docker) copy the dirs in-bounds. Cost: edits aren't live until re-copied.

## nanobot v0.2.1 runtime facts (verified in source/logs — do not re-litigate)

- **cron is a reminder system, not a background-task runner.** Every user cron job fires wrapped in
  "Deliver this reminder to the user now…" (`cli/commands.py`), so the agent *relays* the message
  instead of executing it; recurring jobs also never self-delete. This is why the skills forbid cron
  for job-waiting — both the recurring and one-shot `at` variants failed in practice.
- **Gateway no longer depends on reels at startup (was: "start reels before gateway").** A remote
  MCP that is *reachable but origin-down* (Cloudflare answers the TCP handshake and returns
  502/503/504 because the reels origin :8900 died) used to crash the whole gateway: nanobot's
  `_probe_http_url` was a bare TCP probe, so it passed, nanobot entered `streamable_http_client`,
  the MCP handshake failed mid-stream, and the anyio task-group teardown raised
  `RuntimeError: Attempted to exit cancel scope in a different task` → restart loop → container
  unhealthy → cloudflared's `depends_on: service_healthy` failed. **Fixed** by
  `patches/mcp-probe-origin-aware.patch` (origin-aware HTTP probe; treats `>= 502`,
  `401`/`403` (auth failure — e.g. a wrong/expired reels Cloudflare Access service token, which
  otherwise fails the handshake and crashes the same way), or any connection error as "skip").
  Now a down or mis-credentialed reels is logged `MCP server 'badminton-reels':
  ... unreachable, skipping`, the gateway starts normally, and reels reconnects on a later turn
  once its origin is back (`_connect_mcp` runs per turn; `connect_missing_servers` only connects
  servers not already live). Reels is still a **separate** deployment needing its own supervision
  (`cd /mnt/ssd1/howchien/badminton-reels && uv run badminton-mcp`; `curl 127.0.0.1:8900/healthz`),
  but the gateway is no longer coupled to it. Rebuild after editing nanobot source:
  `docker compose up -d --build`.
- **Per-MCP containers + health-ordered startup.** Compose services are `gateway`, `badminton-db`,
  `cloudflared`, and `ingest` (profile). The gateway is now a pure nanobot host: its Dockerfile COPYs
  `mcps/util/` (not `db_mcp/`/`ingest.py`/`scripts/`), it no longer sets `BADMINTON_DB`, and it has
  `depends_on: { badminton-db: { condition: service_healthy } }` so the db MCP's `/healthz` is green
  before the gateway connects. Verified: gateway logs `MCP server 'badminton-db': connected` over
  HTTP and `util` connected over stdio; `list_tables`/`query` work; `DELETE` is rejected;
  `verify_db` 23/23; parity OK. Only the gateway is tunneled by cloudflared — `badminton-db:8801` is
  internal-only (never host-published). nanobot's **SSRF filtering does NOT apply to configured
  `tools.mcpServers`**, so the internal `http://badminton-db:8801/mcp` URL connects fine.
- **A text-only assistant response ends the turn** (per-session serial; cross-session concurrent,
  gate=3). Hence: no mid-poll text output, and progress display belongs to the UI, not the model.
- **Tool events reach the WebUI only after the whole iteration's tool batch finishes** — hence the
  skill rule "one tool call per response" (batching `get_*_status` with `sleep` delays the progress
  bar by the sleep duration).
- gpt-5.1 (reasoning model) emits **no user-visible text alongside tool calls** — instructions to
  "narrate progress while polling" cannot work; don't try prompt-engineering around it.
- The **legacy** host run (`nanobot gateway` via `scripts/load_env.sh`) is an in-session background
  process — it dies with the session (recurring 502/530s). The reproducible fix now lives in the repo:
  **`docker-compose.yml` + `Dockerfile` + `docs/DEPLOY.md`** run the gateway + its own cloudflared tunnel
  under Docker (`restart: unless-stopped`), with the agent config/brain committed as templates under
  `nanobot/` and the patched nanobot vendored at `vendor/nanobot/`. The remote **reels** server is a
  separate deployment (its own repo/machine) and still needs its own supervision — out of scope here.
- **WebUI auth is delegated to Cloudflare Access via `NANOBOT_WEBUI_TRUST_PROXY=1`** (Docker mode); do
  NOT set a `tokenIssueSecret`. This nanobot version hardened the WS channel two ways, both of which
  fight a Cloudflare-fronted deploy: (1) `WebSocketConfig.wildcard_host_requires_auth` rejects `host`
  `0.0.0.0`/`::` unless `token`/`tokenIssueSecret` is set → else the channel is dropped
  (`websocket channel not available` → `No channels enabled`), port 8765 never binds, and cloudflared
  loops on `dial tcp …:8765: connect: connection refused` while the container still shows **healthy**
  (healthcheck hits :18790, not :8765); (2) `_handle_bootstrap` 401s if a secret is set and 403s
  (`bootstrap is localhost-only`) for non-localhost clients if not — and the WebUI turns BOTH into the
  "Enter the secret configured as tokenIssueSecret" prompt. Since everything via cloudflared is
  non-localhost, a secret-less remote client is blocked and a secret-ful one is prompted. `host` MUST
  stay `0.0.0.0` (cloudflared reaches `gateway:8765` over the compose net), so the fix is the vendored
  patch **`patches/webui-trust-proxy-auth.patch`** + `NANOBOT_WEBUI_TRUST_PROXY: "1"` in
  `docker-compose.yml`: with the env var truthy, the validator passes with no secret and bootstrap
  serves remote clients without one. Safe because 8765 is `expose`-only (only cloudflared → Cloudflare
  Access reaches it; `badmintongpt.nycu-adsl.cc` redirects to the Access login). Fails closed if unset.
  Keep `nanobot/config.json` `token`/`tokenIssueSecret`/`tokenIssuePath` all empty,
  `websocketRequiresToken: false`. (Editing `vendor/` reruns the full nanobot+WebUI image build — slow,
  unlike a config-only change which only re-COPYs a late layer.)

## Patched WebUI (progress bar)

The served WebUI is a **patched rebuild**, not the stock dist: a generic `ToolProgress` card renders a
live progress bar for any tool whose result has numeric `stage`+`total_stages` (e.g. `get_reel_status`).
Source clone: `/mnt/ssd1/howchien/nanobot-webui` (HKUDS/nanobot @ v0.2.1 + `patches/webui-progress.patch`).
Rebuild with `scripts/build_webui.sh`, deploy with `scripts/deploy_webui.sh` (backs up the stock dist to
`dist.orig`, refuses to deploy onto a nanobot version ≠ 0.2.1). **`uv tool upgrade nanobot-ai` wipes the
deployed dist** — re-run deploy (and rebase the patch if the version changed). Do not upgrade casually.

## Message TTS (WebUI speaker button)

A speaker button beside each assistant reply's copy button reads the reply aloud (plain prose only —
code/tables/math/charts/media are skipped). Two vendored patches, full design in `docs/MESSAGE_TTS.md`:
- **`patches/webui-tts-proxy.patch`** (`nanobot/channels/websocket.py`) — a GET-only `/api/tts` route
  (the websockets HTTP parser accepts no other verb) that proxies to the upstream Qwen3-TTS with
  `TTS_API_KEY` injected server-side, buffers the streamed PCM, and wraps it in a WAV header. Gated
  by the same bootstrap token as the other `/api/*` routes; reads `TTS_ENDPOINT`/`TTS_API_MODEL`/
  `TTS_DEFAULT_VOICE`/`TTS_API_KEY` from env. CORS + key-exposure are why it's a server proxy.
- **`patches/webui-tts.patch`** (`vendor/nanobot/webui/`) — speaker button in `MessageBubble.tsx`,
  `useMessageTts` (module-level single player + LRU blob cache + look-ahead playback), `tts-text.ts`
  (mdast walk → spoken prose + sentence segmentation), `useTtsSettings` (voice + auto-prefetch in
  localStorage), and a Speech group in `SettingsView.tsx`. Plain-text extraction is client-side; the
  text is chunked into short GET requests because the proxy is GET-only.
- Audio is fetched as WAV **Blobs with the Bearer token** (not `<audio src>`) so it can be cached for
  instant replays. Trigger modes (Settings): on-demand (default) or auto-prefetch on reply completion.

## When editing nanobot behavior

Routing rules and DB query conventions live in `~/.nanobot/workspace/SOUL.md` (always loaded);
deep schema/enum detail lives in the `skills/badminton-db/` playbook (loaded on demand). Skill
triggering is heuristic, so keep the must-know conventions in SOUL.md and the depth in the skill.
After changing the DB schema, update `mcps/badminton-db/ingest.py` DDL,
`mcps/badminton-db/scripts/verify_db.py`, `skills/badminton-db/references/schema.md`, and the
SOUL.md conventions together.
The async-job wait recipe is owned by `skills/long-mcp-job/` (SOUL rule 3 carries the one-line
summary; `skills/badminton-reels/` is domain knowledge only) — edit them together, then
**re-copy into the workspace** (`scripts/sync_skills.sh`, host mode; or rebuild/restart the
container) and restart the gateway (reels first; see runtime facts above) to pick changes up.
Skills are **copied**, not symlinked, into `~/.nanobot/workspace/skills/` (the
`restrictToWorkspace` boundary rejects symlinked-in dirs — see Gotchas), so a repo edit is not
live until re-copied.
