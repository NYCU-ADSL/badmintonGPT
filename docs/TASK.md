# BadmintonGPT

## Goal

Build an agent connected to multiple badminton-related MCPs and a match DB. When users (the public, coaches, players) ask questions, it can respond using MCP capabilities and find relevant information through the DB and web search.

## Audience

1. General public
2. Coaches and players

## Pain points

GPT, Gemini, Claude, etc. currently cannot find clips of a player's specific tactics or generate highlights on demand. Semantic queries also cannot produce analysis charts.

## How to solve?

1. Use https://github.com/HKUDS/nanobot as the agent.
2. Connect the DB and web search.
3. Connect MCPs and provide templates.
4. Use https://huggingface.co/datasets/howard9199/Badminton/tree/main as the example DB source. Connect ../badminton-reels first, but do not implement its MCP directly yet; first explain how to adapt badminton-reels for use as an agent MCP.

## Final output

A web UI (use nanobot's built-in WebUI directly, ws channel `http://127.0.0.1:8765`).

## Success Metric

Define questions and the corresponding expected calls, then check whether the calls and responses match expectations.

---

## Confirmed decisions (2026-06-05)

| Item | Decision |
|------|------|
| Deliverable for this phase | **Planning + badminton-reels refactoring guide only**; no implementation yet |
| DB format | **SQLite only (relational)**; the LLM handles semantic queries by translating natural language into SQL/filters |
| Web UI | **Use nanobot's built-in UI directly** (no separate frontend) |
| LLM provider | **Configurable/local**; document switching (nanobot supports multiple providers + fallback), without tying it to one vendor |
| Reels tool granularity | **Coarse-grained + asynchronous jobs**: one `generate_reel` returns `job_id`, with separate status/result tools |

### MCP tool scope (confirmed)

The only capability to expose as MCP in this phase:

1. **Generate highlight videos** (wrap the badminton-reels pipeline; coarse-grained + asynchronous jobs)

**Not exposed as MCP yet (revisit later)**:

- Generate analysis charts (charts)
- Find tactical clips semantically (tactic-clips)

**No MCP needed**:

- Query player/match statistics → the agent queries SQLite directly (text-to-SQL).
- Find tactical clips semantically → initially use agent text-to-SQL to filter matching rallies and return clip paths from the DB (no separate MCP).
- Analysis charts → excluded from this phase (reassess once reels MCP works).

---

## System architecture (planned)

```
                         ┌────────────────────────────┐
   User (web UI) ───────▶│   nanobot Agent (loop)      │
                         │  - text-to-SQL DB queries   │
                         │  - call MCP tools           │
                         │  - web search               │
                         └──────┬───────────┬─────────┘
                                │           │
              ┌─────────────────┘           └──────────────────┐
              ▼                                                  ▼
   ┌─────────────────────┐      Cloudflare Tunnel    ┌──────────────────────┐
   │  SQLite match DB     │   + Access service token  │  reels MCP (remote)   │
   │ (ingest HF dataset)  │     (https://.../mcp)     │  Streamable HTTP      │
   │  - shot annotations  │◀── shared data source ──│  bind 127.0.0.1       │
   │  - rallies / scores  │                          │  generate/status/     │
   │  - video clip paths  │                          │  result + /files mp4  │
   └─────────────────────┘                          │ (charts/tactic-clips  │
                                                     │  not MCP yet)         │
                                                     └──────────────────────┘
```

> Note (architecture evolution after implementation; see `DESIGN.md`): implementation changed to
> **independent MCPs**—`badminton-db` became a **separate container** serving streamable HTTP
> (`http://badminton-db:8801/mcp` on the compose network, not public); `util` (sleep) remains stdio,
> launched in-process by the gateway; reels remains remote. DB building is also **decoupled** from
> badminton-reels (vendored parser/models, only `HF_TOKEN` required). The planned capabilities and question bank below are unchanged.

## Component design

### 1. nanobot Agent

- `~/.nanobot/config.json`: declare provider/model (switchable), enable the WebSocket channel, and register MCP servers.
- Agent capabilities:
  - **text-to-SQL**: translate natural-language player/match queries into SQLite queries (without MCP).
  - **MCP tool calls**: reels / charts / tactic-clips.
  - **web search**: add context absent from the DB (player updates, match news, etc.).

### 2. SQLite match DB

- Write an ingestion script to load CSVs from HF dataset `howard9199/Badminton` into SQLite.
- **Actual data volume (verified)**: 32 folders = **27 official 2022 matches + 5 `NYCU_Other_practice` practice clips** (men's/women's singles).
- Planned tables (based on the actual dataset structure):
  - `matches` (match name, tournament, round, players A/B; parseable from folder names)
  - `rallies` (from `RallySeg.csv`, columns: `Score, UpCourt, DownCourt, Start, End, Comment`; Score identifies the rally)
  - `shots` (from `label/set{1,2,3}.csv`, **32 actual columns**):
    `rally, ball_round, time, frame_num, end_frame_num, roundscore_A, roundscore_B, player(A/B), server, type, aroundhead, backhand, hit_height, hit_area, hit_x, hit_y, landing_height, landing_area, landing_x, landing_y, lose_reason, win_reason, getpoint_player, flaw, player_location_area/x/y, opponent_location_area/x/y, db`
- Retain rally IDs in `set_scoreA_scoreB` format (e.g. `1_05_04`), corresponding to files in `rally_video/`.
- **Actual column values (for text-to-SQL reference)**:
  - `type` (shot type): 放小球、挑球、擋小球、殺球、點扣、發短球、推球、切球、過度切球、勾球、長球、發長球、平球、撲球、後場抽平球、防守回抽、防守回挑、未知球種
  - `lose_reason`: 出界、對手落地致勝、未過網、掛網、落點判斷失誤
  - `win_reason`: 對手出界、落地致勝、對手未過網、對手掛網、對手落點判斷失誤
  - `player` / `getpoint_player`: `A` / `B` (map to player names through `matches`/`RallySeg`; for Axelsen vs Lee, A=Viktor AXELSEN and B=LEE Zii Jia)
  - ⚠️ `rally_video/` contains only some rally clips (just eight for this match); ingestion must flag which rallies have actual video files.

### 3. MCP servers (provide templates)

Only reels is implemented in this phase, as a **remote MCP server** (publicly accessible, connected by nanobot through a remote URL):

- Transport: **Streamable HTTP** (not stdio), endpoint `<PUBLIC_BASE_URL>/mcp`.
- Public access: **Cloudflare Tunnel + Access service token** (selected approach). MCP binds to `127.0.0.1`; `cloudflared` exposes `https://reels-mcp.<domain>`; nanobot connects with `CF-Access-Client-Id/Secret`.
- Video return: **downloadable URL** (`<PUBLIC_BASE_URL>/files/{job_id}.mp4`), not a local path; browser playback is proxied through the nanobot backend by default (videos always remain token-protected).

| MCP | Tool | Input | Output |
|-----|------|------|------|
| reels | `generate_reel` | match_name + style/content parameters | `{job_id, state}` |
| reels | `get_reel_status` | job_id | `{state, stage, message, error}` |
| reels | `get_reel_result` | job_id | `{ready, video_url, ...}` |

> ✅ **reels MCP is complete and deployed** (remote `https://reels-mcp.nycu-adsl.cc`, protected by CF Access).
> See `reels_mcp_usage.md` for connection instructions and `REELS_MCP_HANDOFF.md` for the refactoring specification.
> See **`DESIGN.md`** for detailed system design and implementation steps.
> charts and tactic-clips are not MCPs yet: tactic-clips initially returns clip paths through agent text-to-SQL; charts are excluded from this phase.

### 4. Web UI

- Enable nanobot's built-in WebUI directly; first verify conversation and tool-call flows. Display charts/videos as links or embeds.

---

## badminton-reels refactoring direction (this phase: guide first, no code changes)

Current state: `uv run python -m badminton "<match>"` runs an end-to-end pipeline (DataLoader → MatchAnalyzer → LangGraph G-E-RG → Fish TTS → ffmpeg), taking several minutes and depending on ffmpeg/TTS/external APIs.

Refactoring principles (expand in the guide):

1. **Coarse-grained + asynchronous**: expose only `generate_reel` (returns `job_id`) + `get_reel_status` + `get_reel_result`, preventing long tasks from blocking MCP/Agent.
2. **Make the pipeline entry point callable**: extract the CLI flow from `__main__` into a function accepting parameters and returning structured results/output paths, leaving MCP as a thin wrapper.
3. **Job management**: background execution + persisted state (job status, progress, output paths, errors).
4. **Injectable configuration**: allow callers to override API key / provider / model / output directory, instead of reading only `.env`.
5. **Align data sources**: reels and the DB share HF data and path conventions to avoid duplicate downloads and inconsistencies.

> Note: this phase explains how to refactor; it does not directly implement badminton-reels MCP.

---

## Deliverables for this phase

1. System architecture and component design (the first half of this document).
2. **badminton-reels refactoring guide**: functions/interfaces to refactor, job model, configuration injection points, and draft MCP wrapper interface.
3. MCP server template specification (tool signatures and I/O conventions for reels / charts / tactic-clips).
4. Draft SQLite schema + ingestion plan.
5. Success Metric question bank (below).

---

## Success Metric — question bank (based on actual data)

Questions correspond to actual folders, shot-type values, and reasons for winning/losing points. Define expected calls and verifiable answer sources for each, then check actual calls and responses.

> **Ground truth has been computed by running the script** `mcps/badminton-db/scripts/ground_truth.py`
> (stdlib only; builds an in-memory SQLite DB from local shot-by-shot data plus the 32-folder list).
> Shot-by-shot answers apply only to the one fully downloaded local Axelsen vs Lee match (1,213 shots).

| # | User question | Expected call | ✅ Ground truth (computed) |
|---|-----------|---------|----------------------|
| 1 | "Which Axelsen matches are in the database?" | text-to-SQL (`matches`) | **6 matches**: vs GINTING (World Tour Finals), vs GINTING (Indonesia Masters), vs CHOU Tien Chen, vs MOMOTA, vs NARAOKA, vs LEE Zii Jia |
| 2 | "How many points did Axelsen win with smashes in this match?" | text-to-SQL (`type='殺球'` and A wins the point) | **10 smash winners** (52 Axelsen smashes in total) |
| 3 | "What was the most common reason for losing points in this match?" | text-to-SQL (group by `lose_reason`) | **Out of bounds 50** > opponent winner landing in court 34 > did not clear the net 21 > into the net 10 > landing-point misjudgment 1 |
| 4 | "Compare the two players' lift counts" | text-to-SQL (group by `player`, `type='挑球'`) | **Axelsen(A) 116, Lee(B) 86** (202 total) |
| 5 | "What were the scores in each of the three games?" | text-to-SQL (final roundscore) | **Game 1: 19–21, game 2: 21–11, game 3: 23–21** (Axelsen won 2–1; A=Axelsen) |
| 6 | "Find rally clips of Lee's net shots in this match" | text-to-SQL filters rallies → return available video paths | Lee played **183 net shots**, but local `rally_video/` has only **8 files** (`1_12_13,1_17_17,1_19_20,2_01_00,2_10_08,2_18_10,3_08_10,3_22_21`); return only existing ones |
| 7 | "Make a highlight video of this match" | MCP `reels.generate_reel`→`get_reel_status`→`get_reel_result` | Return job_id and eventually an .mp4 path (no SQL ground truth) |
| 8 | "How has Axelsen's world ranking changed since then?" | web search | Not in the DB; external search required (no DB ground truth) |
| 9 | "Which years and competition levels does the database cover?" | text-to-SQL (`matches`) | **All 2022**; **27 official matches + 5 NYCU practice clips** (32 folders total) |

Verification: record the agent's actual tool sequence and final response; compare with expected calls and ensure answers match the table's ground truth / external sources.
(Recompute ground truth: `python3 mcps/badminton-db/scripts/ground_truth.py`.)
