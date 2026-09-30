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
  `generate_reel` takes **`language` (`zh-TW` | `en`)** = narration script + TTS voice + subtitles;
  the agent never computes it — the fork's `mcp.py` fills it from the WebUI language picker
  (`zh-TW`/`zh-CN` → `zh-TW`, else `en`) when the model omits it (explicit value wins).
- **`badminton-video-retrieval`** — a **remote** MCP (deployed at `video-retrieval.nycu-cgvlab.org`,
  behind Cloudflare Access) that does **natural-language semantic video-clip retrieval** over a
  Milvus vector DB. Standard async-job contract (`start_video_retrieval(query, return_mode)` →
  `get_video_retrieval_status` → `get_video_retrieval_result`; plus `get_service_health` /
  `list_milvus_collections`), so it reuses the generic `long-mcp-job` wait recipe. This repo does not
  implement or containerize it — config just points at the remote URL with
  `${VIDEO_RETRIEVAL_CF_CLIENT_ID}`/`${VIDEO_RETRIEVAL_CF_CLIENT_SECRET}` headers. **`query` must be
  English** (the agent translates the user's request); domain playbook in
  `skills/badminton-video-retrieval/`.
- **`badminton-analyze`** — a **remote** MCP (CoachAI, `coachai.cs.nycu.edu.tw/mcp`, bearer token)
  giving **per-match advanced analytics**: `get_backcourt_count`, `get_shot_height`,
  `get_lost_point_distribution`, `get_shot_win_rate`, `get_rally_rest_time`,
  `get_running_distance`, `get_smash_followup_speed`, `verify_match_statistics`. All **synchronous**
  (no job polling). Every tool keys off **`match_id`, a numeric CoachAI id — NOT our folder name**
  (passing a name 400s); it lives in `matches.analyze_match_id` (see Gotchas). This repo neither
  implements nor containerizes it — config points at the remote URL with an
  `Authorization: Bearer ${ANALYZE_MCP_TOKEN}` header. Playbook: `skills/badminton-analyze/`.
- **`mcps/util/server.py`** — local **stdio** MCP `util` with a single `sleep(seconds≤60)` tool;
  exists solely to pace the async-job polling loop (registered with `toolTimeout: 70`). NOT its own
  container — the gateway launches it in-process over stdio.
- **`skills/badminton-db/`, `skills/badminton-reels/`, `skills/badminton-analyze/`,
  `skills/long-mcp-job/`** — `SKILL.md`
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
- `nanobot/config.json` — providers, websocket channel (:8765), `tools.mcpServers` (all five MCPs):
  `badminton-db` = `{ "type": "streamableHttp", "url": "http://badminton-db:8801/mcp",
  "enabledTools": [...] }` (no auth); `util` = `{ "type": "stdio", "command": "python3",
  "args": ["/app/mcps/util/server.py"], "enabledTools": ["sleep"], "toolTimeout": 70 }`;
  `badminton-reels` = remote `streamableHttp` at `https://reels-mcp.nycu-adsl.cc/mcp` with
  `CF-Access-Client-Id`/`-Secret` headers (`${REELS_CF_CLIENT_ID}`/`${REELS_CF_CLIENT_SECRET}`);
  `badminton-video-retrieval` = remote `streamableHttp` at
  `https://video-retrieval.nycu-cgvlab.org/mcp` with the same CF headers
  (`${VIDEO_RETRIEVAL_CF_CLIENT_ID}`/`${VIDEO_RETRIEVAL_CF_CLIENT_SECRET}`);
  `badminton-analyze` = remote `streamableHttp` at `https://coachai.cs.nycu.edu.tw/mcp` with
  `Authorization: Bearer ${ANALYZE_MCP_TOKEN}` (bearer, **not** Cloudflare Access — the only MCP
  that breaks the `<NAME>_CF_CLIENT_ID/SECRET` convention).
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
- `vendor/nanobot/` — our **fork** of nanobot (HKUDS/nanobot v0.2.1, tracked via git subtree;
  pristine base tagged `nanobot-base-v0.2.1`), vendored so the Docker image builds the customized
  WebUI hermetically. Edit it directly; our delta = `git diff nanobot-base-v0.2.1..HEAD -- vendor/nanobot`.
  Upstream upgrades are a `git subtree pull` merge, not a patch re-apply (see `vendor/README.md`).

Requirements/spec: `docs/TASK.md`. Full design + resolved decisions: `docs/DESIGN.md` (§8 records the actual
nanobot v0.2.1 facts). Setup walkthrough: `README.md`.

## Data model & flow

HuggingFace dataset `howard9199/Badminton` **+ any `--local-data DIR`** →
`mcps/badminton-db/ingest.py` → `data/badminton.db` (SQLite). Three tables: `matches`
(**194 folders** = 189 official + 5 NYCU practice, 2022–2024), `rallies`, `shots`.
`matches.source` records which dataset a folder came from (`hf` = 32, `Data-old` = 162) and
`matches.analyze_match_id` carries the CoachAI id for the `badminton-analyze` MCP (188 mapped).
The second source is `todo0819/Data-old.zip` (190 folders, a superset of the HF set — its 27
overlapping folders are byte-identical and deduped away): unpack CSVs + a video manifest with
`scripts/extract_data_old.py`, then `ingest.py --local-data data/Data-old`. The archive's 39 GB of
`rally_video/` is **not** kept here — `scripts/extract_data_old.py --videos-to <reels>/data/Data`
puts the ~26 GB the HF dataset lacks on the badminton-reels host (its `DataLoader` now prefers local
files over HF, so those matches are renderable). `scripts/upload_data_old_to_hf.py` pushes the new
CSVs to HF for a from-scratch rebuild — it needs a **write**-scoped `HF_TOKEN` (the current login is
read-only, so this step is still pending).
`ingest.py` is now **decoupled from `../badminton-reels`** — it imports from the vendored
`mcps/badminton-db/ingest_lib/` (`RallySegment`/`ShotLabel` models, `parse.extract_tournament_round`,
a thin HF `DataLoader`) instead of injecting `$REELS_SRC` or importing `badminton.data_loader` /
`badminton.models`. The DB build therefore needs **only `HF_TOKEN`** (no `OPENAI`/`FISH`/reels).
`shots` now covers **138 matches** (~117k shots) and `rallies` **169**; the rest (practice clips and
archive folders shipped without annotation) have catalog metadata only. Since one query can now span
138 matches, **per-match questions MUST filter by `match_name`**.

Ground truth for verification lives in `mcps/badminton-db/scripts/ground_truth.py` (in-memory oracle)
and is asserted by `mcps/badminton-db/scripts/verify_db.py`. `scripts/test_decouple_parity.py` (same
dir) checks
the vendored `ingest_lib/` parsing still matches the upstream reels parsing. The success-metric bank
(9 original questions + 2 for the merged data / badminton-analyze) is in `docs/TASK.md` /
`eval/run_eval.py`.

## Commands

```bash
# --- setup (once) ---
uv sync                                   # build .venv (py3.12: mcp, huggingface_hub, pydantic, websockets)
uv tool install nanobot-ai && nanobot onboard
./scripts/sync_skills.sh                  # COPY skills/* → ~/.nanobot/workspace/skills/ (NOT symlink; see Gotchas)
cp .env.example .env                      # fill OPENAI_API_KEY + REELS_CF_CLIENT_ID/SECRET

# --- build / verify the DB (all paths under mcps/badminton-db/) ---
.venv/bin/python scripts/extract_data_old.py                # unpack todo0819/Data-old.zip: CSVs + video manifest -> data/Data-old/
.venv/bin/python scripts/extract_data_old.py --videos-to /mnt/ssd1/howchien/badminton-reels/data/Data   # ~26 GB of rally clips -> the reels host
.venv/bin/python mcps/badminton-db/ingest.py --local-data data/Data-old   # THE build: HF + the merged archive (CSVs only, no videos)
.venv/bin/python mcps/badminton-db/ingest.py                # HF only (32 folders) — leaves the merged matches out
.venv/bin/python mcps/badminton-db/ingest.py --catalog-only # only the matches catalog
.venv/bin/python mcps/badminton-db/ingest.py --only <folder|name> --limit N   # subset (testing)
.venv/bin/python mcps/badminton-db/scripts/verify_db.py     # 30 assertions vs ground truth
.venv/bin/python scripts/upload_data_old_to_hf.py --dry-run # what the HF push would upload (needs a WRITE HF_TOKEN to run for real)
.venv/bin/python mcps/badminton-db/scripts/ground_truth.py  # recompute the oracle numbers
.venv/bin/python mcps/badminton-db/scripts/test_decouple_parity.py  # vendored ingest_lib vs upstream reels parsing

# --- run the db MCP standalone ---
MCP_TRANSPORT=stdio .venv/bin/python mcps/badminton-db/scripts/test_db_mcp.py   # stdio smoke test, no nanobot
BADMINTON_DB=$PWD/data/badminton.db MCP_HOST=127.0.0.1 .venv/bin/python mcps/badminton-db/server.py   # http://127.0.0.1:8801/mcp (host/dev; server.py has NO default DB path)

# --- test any MCP server (conformance probe, used by other sub-projects too) ---
.venv/bin/python -m mcp_test https://reels-mcp.nycu-adsl.cc/mcp \
  --header "CF-Access-Client-Id: $REELS_CF_CLIENT_ID" \
  --header "CF-Access-Client-Secret: $REELS_CF_CLIENT_SECRET"

# --- rebuild the WebUI for local host/dev (Docker rebuilds it automatically via the hatch hook) ---
( cd vendor/nanobot/webui && bun run build )   # outputs to vendor/nanobot/nanobot/web/dist

# --- run the agent (host/dev mode) ---
source scripts/load_env.sh                # exports OPENAI_API_KEY + CF_* from ./.env (no fallback)
BADMINTON_DB=$PWD/data/badminton.db MCP_HOST=127.0.0.1 .venv/bin/python mcps/badminton-db/server.py &  # db MCP over HTTP (host config points here)
nanobot gateway                           # WebUI at http://127.0.0.1:8765 (util stays in-process stdio)
nanobot agent -m "Which Axelsen matches are in the database?"   # one-shot headless

# --- reproducible deploy (Docker Compose + Cloudflare tunnel; see docs/DEPLOY.md) ---
docker compose --profile ingest run --rm ingest   # build ./data/badminton.db on badmintongpt-db image (needs only HF_TOKEN)
docker compose up -d --build                       # gateway (patched WebUI) + badminton-db + cloudflared

# --- success-metric eval (drives `nanobot agent`, parses ↳ tool hints) ---
.venv/bin/python eval/run_eval.py --skip-reels   # 10 cheap cases
.venv/bin/python eval/run_eval.py                # all 11 (Q7 triggers a real remote render)
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
  now holds **138** matches, **per-match questions MUST filter by `match_name`** or they sum across
  all of them — and with 194 folders the same two players now appear in many matches, so narrow with
  `tournament`/`year`/`round` too.
- **`analyze_match_id` is CoachAI's numeric id, not anything of ours.** The `badminton-analyze` MCP
  addresses a match by its position in `https://coachai.cs.nycu.edu.tw:55000/api/db-api/match`
  **+ 4** (valid range 4–371; verified: our Axelsen–Lee match == 123, whose B net shots = 183 matches
  `verify_db.py` exactly, which also confirms their A/B binding equals ours). `ingest.py` fetches
  that list and maps it by normalized folder name (fail-soft → NULL; `--no-analyze-ids` skips).
  Passing a folder/match name to the MCP instead returns `Failed to fetch set data: 400`, and its
  `players` field is always the literal `"Player A"/"Player B"` — real names must come from
  `matches.player_a/_b`.
- **One Data-old label CSV is mojibake upstream** (`AN_Se_Young_CHEN_Yu_Fei_Malaysia_Open_2023_SF`
  set2): its `type` values arrive as unrecoverable garbage (literal `?` = bytes already lost, so no
  re-decode helps). `ingest.clean_shot_type` folds those onto the existing `未知球種` enum member so
  the documented enum stays closed; `verify_db.py` asserts no `?` survives in `shots.type`.
  Genuinely new labels (`死球`, from the 2023/2024 matches) pass through untouched.
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
  (`NANOBOT_MODEL=gpt-5.5`). nanobot **errors on an unset `${VAR}`**, so both modes provide a
  fallback: `scripts/load_env.sh` exports `NANOBOT_MODEL:-gpt-5.5` (host) and `docker-compose.yml`
  uses `${NANOBOT_MODEL:-gpt-5.5}` (Docker). The WebUI Settings panel reads config **unresolved**
  (so it wouldn't expand `${VAR}`); the fork's `settings_api.py` change makes it
  resolve the model for display (like `api_base`) and **not clobber** the `${NANOBOT_MODEL}` ref
  when the WebUI echoes the resolved value back on save. (Bootstrap/header already uses the resolved
  runtime model, so only Settings needed it.)
- **A second, switchable "Custom" model** rides on nanobot's `model_presets` (the WebUI Settings model
  picker shows it next to the GPT-5.5 default; default stays GPT-5.5). `nanobot/config.json` wires
  `providers.custom` = `{apiKey: "${CUSTOM_MODEL_API_KEY}", apiBase: "${CUSTOM_MODEL_API_BASE}"}` (any
  OpenAI-compatible endpoint) and `model_presets.custom` = `{model: "${CUSTOM_MODEL_API_MODEL}",
  provider: "custom"}`. All three `CUSTOM_MODEL_API_*` come from `.env`; same unset-`${VAR}`-crash rule
  applies, so `scripts/load_env.sh` and `docker-compose.yml` export **empty** fallbacks (an empty var
  is "set" → no crash; an unset one crashes). The preset is inert until all three are filled — selecting
  it with no `apiKey` raises `No API key configured for provider 'custom'` at turn time (not startup).
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
  the fork's origin-aware `mcp.py` probe (treats `>= 502`,
  `401`/`403` (auth failure — e.g. a wrong/expired reels Cloudflare Access service token, which
  otherwise fails the handshake and crashes the same way), or any connection error as "skip").
  Now a down or mis-credentialed reels is logged `MCP server 'badminton-reels':
  ... unreachable, skipping`, the gateway starts normally, and reels reconnects on a later turn
  once its origin is back (`_connect_mcp` runs per turn; `connect_missing_servers` only connects
  servers not already live). Reels is still a **separate** deployment needing its own supervision
  (`cd /mnt/ssd1/howchien/badminton-reels && uv run badminton-mcp`; `curl 127.0.0.1:8900/healthz`),
  but the gateway is no longer coupled to it. Rebuild after editing nanobot source:
  `docker compose up -d --build`.
- **A remote MCP's session expiring used to kill that MCP until a gateway restart — now self-heals.**
  Streamable-HTTP servers issue an `Mcp-Session-Id` at `initialize` and answer **404
  `Session not found`** once they forget it (restart / idle GC); the SDK raises
  `McpError: Session terminated` and nanobot surfaces the useless `MCP tool call failed: McpError`.
  Upstream never recovered — the session object stays dead and `connect_missing_servers` only
  connects servers *missing* from `_mcp_stacks`, so the still-present dead connection is never
  re-initialized (hit 2026-09-04: `badminton-analyze` fine at 06:55, then 19 straight failures from
  08:12; the remote itself was healthy — a fresh `initialize` + `tools/call` returned data). Fixed
  in the fork (`vendor/nanobot/nanobot/agent/tools/mcp.py`): the wrappers detect that error,
  reconnect just that server in place and retry once, serialized per server so a parallel tool batch
  reconnects once. Verified live by restarting `badminton-db` mid-call. **Diagnosing this class of
  bug**: `docker compose logs gateway | grep -B2 McpError` shows the real `ErrorData(...)`, then
  probe the remote directly — a fresh `initialize` that works while the gateway keeps failing means
  a stale session, not a bad token/param.
- **Per-MCP containers + health-ordered startup.** Compose services are `gateway`, `badminton-db`,
  `cloudflared`, and `ingest` (profile). The gateway is now a pure nanobot host: its Dockerfile COPYs
  `mcps/util/` (not `db_mcp/`/`ingest.py`/`scripts/`), it no longer sets `BADMINTON_DB`, and it has
  `depends_on: { badminton-db: { condition: service_healthy } }` so the db MCP's `/healthz` is green
  before the gateway connects. Verified: gateway logs `MCP server 'badminton-db': connected` over
  HTTP and `util` connected over stdio; `list_tables`/`query` work; `DELETE` is rejected;
  `verify_db` 23/23; parity OK. Only the gateway is tunneled by cloudflared — `badminton-db:8801` is
  internal-only (never host-published). nanobot's **SSRF filtering does NOT apply to configured
  `tools.mcpServers`**, so the internal `http://badminton-db:8801/mcp` URL connects fine.
- **Reply language + reels `language` both come from the WebUI language picker.** The WebUI sends
  `locale` on every message frame → `InboundMessage.metadata["locale"]` → (a) `loop.py` adds a "User
  UI language: …" runtime line that SOUL.md's language rule honors, and (b) `agent/tools/mcp.py`
  `_fill_language_from_locale` defaults any MCP tool's schema-declared `language` argument from it
  (exact → same base language → `en` → unset). Non-WebUI channels send no locale → English default,
  reels server default (`zh-TW`). Both are fork changes; `vendor/README.md` "reply-language".
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
  stay `0.0.0.0` (cloudflared reaches `gateway:8765` over the compose net), so the fix is the fork's
  trust-proxy change in `channels/websocket.py` + `NANOBOT_WEBUI_TRUST_PROXY: "1"` in
  `docker-compose.yml`: with the env var truthy, the validator passes with no secret and bootstrap
  serves remote clients without one. Safe because 8765 is `expose`-only (only cloudflared → Cloudflare
  Access reaches it; `badmintongpt.nycu-adsl.cc` redirects to the Access login). Fails closed if unset.
  Keep `nanobot/config.json` `token`/`tokenIssueSecret`/`tokenIssuePath` all empty,
  `websocketRequiresToken: false`. (Editing `vendor/` reruns the full nanobot+WebUI image build — slow,
  unlike a config-only change which only re-COPYs a late layer.)

## Customized WebUI (fork)

The served WebUI is built from our **fork** (`vendor/nanobot/webui/`), not the stock dist. Among the
changes: a generic `ToolProgress` card renders a live progress bar for any tool whose result has
numeric `stage`+`total_stages` (e.g. `get_reel_status`). The Docker image rebuilds the WebUI
automatically (hatch hook, `NANOBOT_FORCE_WEBUI_BUILD=1`) — there is no separate clone, no
`build_webui.sh`/`deploy_webui.sh`, and no dist-overlay onto a `nanobot-ai` PyPI install. For local
host/dev, rebuild directly: `( cd vendor/nanobot/webui && bun run build )` → outputs to
`vendor/nanobot/nanobot/web/dist`. Full list of fork changes + the upstream-merge workflow:
`vendor/README.md`.

## Message TTS (WebUI speaker button)

A speaker button beside each assistant reply's copy button reads the reply aloud (plain prose only —
code/tables/math/charts/media are skipped). Two fork changes, full design in `docs/MESSAGE_TTS.md`:
- **`/api/tts` proxy** (`nanobot/channels/websocket.py`) — a GET-only `/api/tts` route
  (the websockets HTTP parser accepts no other verb) that proxies to the upstream Qwen3-TTS with
  `TTS_API_KEY` injected server-side **via the openai SDK** (`AsyncOpenAI(base_url=TTS_API_BASE)
  .audio.speech.create`, `response_format="pcm"`), reads the PCM, and wraps it in a WAV header. Gated
  by the same bootstrap token as the other `/api/*` routes; reads `TTS_API_BASE`/`TTS_API_MODEL`/
  `TTS_DEFAULT_VOICE`/`TTS_API_KEY` from env. CORS + key-exposure are why it's a server proxy.
- **speaker button** (`vendor/nanobot/webui/`) — in `MessageBubble.tsx`,
  `useMessageTts` (module-level single player + LRU blob cache + look-ahead playback), `tts-text.ts`
  (mdast walk → spoken prose + sentence segmentation), `useTtsSettings` (voice + auto-prefetch in
  localStorage), and a Speech group in `SettingsView.tsx`. Plain-text extraction is client-side; the
  text is chunked into short GET requests because the proxy is GET-only.
- Audio is fetched as WAV **Blobs with the Bearer token** (not `<audio src>`) so it can be cached for
  instant replays. Trigger modes: on-demand (default) or auto-prefetch on reply completion.
- **Defaults come from the repo-root `.env`**, not just hard-coded: the gateway puts
  `{default_voice: TTS_DEFAULT_VOICE, auto_prefetch: TTS_AUTO_PREFETCH, max_segment_chars:
  min(TTS_SEGMENT_CHARS, TTS_MAX_INPUT_CHARS)}` into the `/webui/bootstrap` JSON, and `useTtsSettings`
  uses them as the initial values. Precedence = per-browser localStorage
  override (set only when a user flips the Settings → Speech control) **>** `.env` default **>**
  built-in. So a later `.env` change stays live for browsers that never toggled (we persist only on
  explicit change, never on mount). `TTS_AUTO_PREFETCH` is truthy-parsed (`1/true/yes/on`).
- **Latency knobs (`TTS_SEGMENT_CHARS` / `TTS_MAX_INPUT_CHARS` / `TTS_TIMEOUT_S`) are env-driven** —
  the bottleneck for long replies is **synthesis TIME, not size**: the `/api/tts` proxy is
  non-streaming (buffers the whole segment's PCM before returning) and upstream synthesis is
  ~linear (~0.1 s/char measured). So the client chunks each reply into `TTS_SEGMENT_CHARS`-sized
  pieces (default **60** ≈ first sound ~6 s; was effectively 400 ≈ ~34 s → felt broken) shipped via
  bootstrap; `TTS_MAX_INPUT_CHARS` (default **300**, was a hardcoded 1200 that could exceed the
  timeout) 413s anything bigger. Invariant **`TTS_SEGMENT_CHARS ≤ TTS_MAX_INPUT_CHARS`** (bootstrap
  clamps). These are **runtime env** (read at process start + per-bootstrap), so re-tuning is `.env`
  + `docker compose up -d` — **no image rebuild**, unlike editing the `vendor/` source. URL length is
  NOT the constraint (400 CJK chars URL-encode to ~3.6 KB, far under `MAX_LINE_LENGTH` 8192). Full
  rationale + measurements in `docs/MESSAGE_TTS.md` §5.4.

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
