# BadmintonGPT — System design (DESIGN)

> This document describes BadmintonGPT's **detailed architecture** and **implementation approach (how to write it)**.
> See [`TASK.md`](./TASK.md) for requirements context.
> **reels MCP server is complete and deployed** (remote, `https://reels-mcp.nycu-adsl.cc`, CF Access protected). This document treats it as an **existing external service**; see [`reels_mcp_usage.md`](./reels_mcp_usage.md) for connection instructions and [`REELS_MCP_HANDOFF.md`](./REELS_MCP_HANDOFF.md) for its internal refactoring specification.

> 📌 Looking for the **implemented and verified current state**, rather than the proposal? Jump to
> [Implemented and verified (nanobot v0.2.1)](#implemented-and-verified-nanobot-v021-2026-06-06) at the end.

## Contents

1. [Purpose and scope](#1-purpose-and-scope)
2. [System overview](#2-system-overview)
3. [Detailed component design](#3-detailed-component-design)
4. [Key data flows (sequence)](#4-key-data-flows-sequence)
5. [Security and deployment](#5-security-and-deployment)
6. [Implementation steps (how to write it)](#6-implementation-steps-how-to-write-it-recommended-order)
7. [Testing and acceptance (Success Metric)](#7-testing-and-acceptance-success-metric)
8. [Confirmed decisions](#8-confirmed-decisions-previous-questions-resolved)
9. [Implemented and verified (nanobot v0.2.1)](#implemented-and-verified-nanobot-v021-2026-06-06)

---

## 1. Purpose and scope

Build a badminton agent around **nanobot** that autonomously chooses among the following when a user asks a question in the web UI:
- **SQLite match DB** (text-to-SQL for players/matches/shot-by-shot statistics and tactical rally clips)
- **reels MCP** (asynchronous highlight video generation)
- **web search** (external information absent from the DB)

This document covers four parts **still to be implemented** (excluding the completed reels MCP):
1. nanobot agent configuration and tool-routing strategy
2. SQLite DB schema and ingestion
3. DB access (**local badminton-db MCP**: `list_tables`/`describe_table`/`query` (SELECT-only) + **badminton-db skill** playbook)
4. Web UI and Success-Metric acceptance harness

| Component | Status | Section |
|------|------|-----------|
| reels MCP server | ✅ Complete and deployed | §3.4 (contract/integration) |
| reels skill playbook | ⬜ To do | §3.4.1 |
| nanobot agent configuration | ⬜ To do | §3.1 |
| SQLite DB + ingestion | ⬜ To do (matches=all 32, shots=1 local match) | §3.2 |
| DB access (local badminton-db MCP + skill playbook) | ⬜ To do | §3.3 |
| web search | ⬜ To do (enable in configuration) | §3.5 |
| Web UI (built into nanobot) | ⬜ To do (enable in configuration) | §3.6 |
| Acceptance harness | ⬜ To do | §7 |

---

## 2. System overview

```
                                  ┌──────────────────────────────────────┐
                                  │            User (browser)                │
                                  └───────────────────┬──────────────────┘
                                  WebSocket (ws://127.0.0.1:8765, through cloudflared tunnel)
                                                      │
                          ┌───────────────────────────▼───────────────────────────┐
                          │      nanobot Agent loop (gateway container: pure host)    │
                          │  providers (switchable) · SOUL.md (brief routing)           │
                          │  skills(playbooks)：badminton-db/badminton-reels/        │
                          │                     long-mcp-job                          │
                          │  util MCP (stdio, in-process：sleep)                      │
                          └──────┬───────────────┬──────────────────┬──────────────┘
                       streamableHttp        streamableHttp        tools.web
                       (compose network)      (CF Access)           │ (search+fetch)
                ┌──────────┴───────────┐  ┌──────┴──────────────┐  ┌──┴───────────┐
                ▼                      │  ▼                     │  ▼              │
   ┌───────────────────────────────┐  │ ┌──────────────────────┴┐ ┌─────────────┐
   │ badminton-db MCP (own container) │ │ │ reels MCP (remote, done)│ │ Web Search  │
   │ FastMCP streamable-http       │  │ │ generate_reel /        │ │ (duckduckgo)│
   │ http://badminton-db:8801/mcp  │  │ │ get_reel_status /      │ └─────────────┘
   │  list_tables / describe_table │  │ │ get_reel_result /      │
   │  / query (SELECT-only)        │  │ │ GET /files/{id}.mp4    │
   │  + GET /healthz               │  │ └──────────▲─────────────┘
   └────────────▲──────────────────┘  │            │ Shared data source
                │                      │            │
   ┌────────────┴──────────────┐ ingest container ┌─┴──────────────────────────┐
   │  badminton.db (SQLite)    │◀─(profile)────│  HuggingFace dataset        │
   │  matches/rallies/shots    │  ingest_lib   │  howard9199/Badminton       │
   └───────────────────────────┘ (reels-decoupled)└─────────────────────────────┘
```

> Deployment: each MCP owned by this repo is independent. badminton-db runs in a **separate container**,
> serving streamable HTTP at `http://badminton-db:8801/mcp` on the compose network (no auth, never public).
> util remains **stdio**, launched in-process by gateway (no separate container); reels remains **remote**
> (`https://reels-mcp.nycu-adsl.cc/mcp`, CF Access). DB building (ingest container/profile) is
> **decoupled** from badminton-reels, with parser/models vendored in `mcps/badminton-db/ingest_lib/`; only HF_TOKEN is required.

**Design principles**
- **Single source of truth**: DB ingestion and reels share the HF dataset. Parsing logic (players A/B, rally_id format) originally reused badminton-reels and is **now vendored in `mcps/badminton-db/ingest_lib/`** (same parsing behavior as reels, guarded by parity tests); ingest no longer imports badminton-reels.
- **MCP connection layer + skill playbook layer (the mainstream 2026 hybrid)**: all data/tool access goes through **MCP**—badminton-db (own container, streamable HTTP `:8801/mcp`) and badminton-reels (remote). **Each capability has a skill playbook** (badminton-db, badminton-reels) containing only triggers, conventions, MCP tool selection, and orchestration, not access itself. "MCP scales systems; skills scale behavior."
- **Deterministic DB access**: queries use the typed, auditable MCP query tool, not CLI execution through exec. The MCP server enforces SELECT-only + mode=ro.
- **Autonomous agent routing**: keep brief routing hints in the system prompt; the DB skill playbook supplies details, while MCP tools perform actual access.

---

## 3. Detailed component design

### 3.1 nanobot Agent

#### 3.1.1 ~/.nanobot/config.json (complete example)

```jsonc
{
  "providers": {
    // OpenAI by default; inject apiKey through ${ENV}. Add other providers when switching.
    "openai": { "apiKey": "${OPENAI_API_KEY}" }
  },

  "agents": {
    "defaults": {
      "modelPreset": "deep",
      "fallbackModels": ["fast"],
      "temperature": 0.1,           // Low temperature for stable text-to-SQL
      "reasoningEffort": "medium",
      "timezone": "Asia/Taipei"
    }
  },
  "modelPresets": {
    // All OpenAI; adjust model names to available versions (badminton-reels currently uses gpt-5.1)
    "deep": { "provider": "openai", "model": "gpt-5.1",      "reasoningEffort": "high" },
    "fast": { "provider": "openai", "model": "gpt-5.1-mini", "temperature": 0.2 }
  },

  "channels": {
    "sendProgress": true,
    "sendToolHints": true,          // Acceptance harness needs visible tool calls
    "websocket": { "enabled": true, "port": 8765 }
  },

  // mcpServers (top-level): DB MCP (own container, streamable HTTP) + remote reels MCP (streamableHttp, tested in usage.md)
  "mcpServers": {
    "badminton-db": {
      "type": "streamableHttp",
      "url": "http://badminton-db:8801/mcp",
      "enabledTools": ["list_tables", "describe_table", "query"]
      // Separate container, streamable HTTP; no auth (compose network only, never public)
      // Exposes list_tables / describe_table / query(SELECT-only) + GET /healthz (see §3.3)
    },
    "util": {
      "type": "stdio",
      "command": "python3",
      "args": ["/app/mcps/util/server.py"],
      "enabledTools": ["sleep"],
      "toolTimeout": 70
      // stdio, launched in-process by gateway (no separate container); sleep(seconds≤60) paces async-job polling
    },
    "badminton-reels": {
      "type": "streamableHttp",
      "url": "https://reels-mcp.nycu-adsl.cc/mcp",
      "headers": {
        "CF-Access-Client-Id": "${REELS_CF_CLIENT_ID}",
        "CF-Access-Client-Secret": "${REELS_CF_CLIENT_SECRET}"
      },
      "toolTimeout": 120,
      "enabledTools": ["generate_reel", "get_reel_status", "get_reel_result"]
    }
  },

  "tools": {
    "web": {
      "enable": true,
      "search": { "provider": "duckduckgo" },   // No API key; works out of the box
      "fetch":  { "useJinaReader": true }
    }
    // No exec needed: DB uses badminton-db MCP; skills are playbooks only (no scripts to execute)
  }
}
```

> reels uses type:streamableHttp (remote, CF Access, verified); badminton-db also uses type:streamableHttp but points to its own compose-network container at `http://badminton-db:8801/mcp` (no auth, never public); util is in-process stdio. **Host/dev mode**: run DB MCP locally over HTTP with `MCP_HOST=127.0.0.1 python mcps/badminton-db/server.py`, point badminton-db in the host's `~/.nanobot/config.json` to `http://127.0.0.1:8801/mcp`, and keep util as stdio (`python mcps/util/server.py`).
> **Skill discovery path**: nanobot automatically discovers the badminton-db playbook in workspace `skills/` (documented by DeepWiki) or `~/.nanobot/skills/`; verify the actual path for the nanobot version (see §8).

#### 3.1.2 Environment variables (.env / systemd EnvironmentFile)
```
OPENAI_API_KEY=...
REELS_CF_CLIENT_ID=...           # Cloudflare Access service token for reels MCP
REELS_CF_CLIENT_SECRET=...
HF_TOKEN=...                     # Required only by the ingest container (DB build)
BADMINTONGPT_HOME=/mnt/ssd1/howchien/badmintonGPT   # Project root
```
- The gateway container **no longer** sets BADMINTON_DB: the DB moved into the badminton-db container (which sets BADMINTON_DB to the mounted data/badminton.db); gateway connects only over HTTP.
- The ingest container (DB build) **requires only HF_TOKEN**; REELS_SRC / REELS_SRC_HOST are no longer needed (removed from .env.example/compose; see decoupling in §3.2.2).
- Load these variables before starting nanobot (systemd EnvironmentFile=, direnv, or --env-file).

#### 3.1.3 System prompt (brief routing)
**Put details in the corresponding skill playbooks**: DB schema/enums → badminton-db (§3.3); reels async orchestration/conventions → badminton-reels (§3.4.1). Keep only **persona + routing hints** in the system prompt to save context:

```
You are BadmintonGPT, serving general audiences, coaches, and players.

Routing principles:
1) Any question about existing match data in the database (a player's matches, shot-type counts, reasons
   for winning/losing points, scores, rally clips featuring specific tactics/shot types): consult the
   badminton-db skill (enum values, A/B mappings, examples), then call badminton-db MCP query/list_tables/describe_table
   (query accepts only a single SELECT; rally clips require has_video=1).
2) User wants a highlight video: consult the badminton-reels skill (asynchronous orchestration,
   match_name conventions, video_url presentation), then call reels MCP generate_reel /
   get_reel_status / get_reel_result。
3) External information absent from the DB (latest world rankings, player updates, match news): use web search.

Response principles: lead with conclusions and key numbers; include supporting SQL or source links when needed.
```

> Design focus: details needed only for DB questions (schema/enums) belong in the progressively disclosed skill playbook, not the permanent system prompt. Actual access is performed deterministically by badminton-db MCP tools, regardless of whether a skill triggers.

---

### 3.2 SQLite match DB

#### 3.2.1 Schema（DDL）

```sql
CREATE TABLE matches (
  folder       TEXT PRIMARY KEY,   -- HF folder name (including .mp4 suffix)
  name         TEXT,               -- Readable name without suffix
  tournament   TEXT,               -- Parsed from name (nullable)
  round        TEXT,               -- Finals/Semifinals… (nullable)
  player_a     TEXT,               -- Corresponds to shots.player='A'
  player_b     TEXT,               -- Corresponds to shots.player='B'
  year         INTEGER,            -- All 2022
  is_practice  INTEGER DEFAULT 0   -- NYCU_Other_practice* = 1
);

CREATE TABLE rallies (
  match_folder   TEXT REFERENCES matches(folder),
  rally_id       TEXT,             -- "set_scoreA_scoreB", e.g. 1_05_04
  set_no         INTEGER,
  score_a        INTEGER,
  score_b        INTEGER,
  start_frame    INTEGER,
  end_frame      INTEGER,
  has_video      INTEGER DEFAULT 0,-- Whether the file actually exists in rally_video/ (critical!)
  video_filename TEXT,             -- E.g. 1_05_04.mp4 (when has_video=1)
  PRIMARY KEY (match_folder, rally_id)
);

CREATE TABLE shots (
  match_folder    TEXT REFERENCES matches(folder),
  set_no          INTEGER,
  rally           INTEGER,         -- Rally number within the game
  ball_round      INTEGER,
  player          TEXT,            -- 'A'|'B'
  server          TEXT,
  type            TEXT,            -- Shot type (Chinese enum)
  aroundhead      INTEGER,
  backhand        INTEGER,
  hit_area        INTEGER,
  landing_area    INTEGER,
  lose_reason     TEXT,
  win_reason      TEXT,
  getpoint_player TEXT,            -- 'A'|'B'
  roundscore_a    INTEGER,
  roundscore_b    INTEGER
  -- Add other coordinate columns (hit_x/y, landing_x/y, location_*) as needed
);

-- Recommended indexes
CREATE INDEX idx_shots_match_type    ON shots(match_folder, type);
CREATE INDEX idx_shots_match_player  ON shots(match_folder, player);
CREATE INDEX idx_rallies_match_video ON rallies(match_folder, has_video);
```

#### 3.2.2 Ingestion design (mcps/badminton-db/ingest.py)

Responsibility: HF dataset → badminton.db. **Decoupled from badminton-reels**: the former sys.path injection
of $REELS_SRC and imports of badminton.data_loader / badminton.models have been removed. Parsing logic and models
(RallySegment/ShotLabel, parse.extract_tournament_round, a thin HF DataLoader) are **vendored
in mcps/badminton-db/ingest_lib/**; ingest.py now uses from ingest_lib import .... Thus DB building **requires
only HF_TOKEN**, without OPENAI_API_KEY / Fish dependencies or badminton-reels source on the machine.
REELS_SRC / REELS_SRC_HOST were removed from .env.example and the compose ingest service. One-time build:
`docker compose --profile ingest run --rm ingest` (runs on the badmintongpt-db image and produces ./data/badminton.db).

**Scope for this phase (confirmed)**: initially load heavy shot-by-shot data (rallies + shots) **only for the one locally downloaded match** (Axelsen vs Lee). Populate the matches catalog with **all 32 match names** (HF file listing only, no downloads) so Q1 (Axelsen's matches) and Q9 (years/levels) remain answerable.

Steps:
1. matches catalog (all 32): use `huggingface_hub.HfApi().list_repo_files("howard9199/Badminton")` to obtain 32 folder names (**without downloading contents**) and insert each into matches:
   - folder (with .mp4), name (without .mp4, **the match_name passed to reels**);
   - tournament/round: use vendored `ingest_lib.parse.extract_tournament_round()`;
   - `is_practice = name.startswith("NYCU_Other_practice")`、`year=2022`；
   - player names: fill player_a/player_b when parseable from the name; practice clips may leave them empty.
2. Shot-by-shot data (locally downloaded matches, currently one): for each **locally existing** match folder:
   - use the HF DataLoader and RallySegment/ShotLabel models from vendored ingest_lib to obtain
     rally_segments and per-game labels, populate matches.player_a/b, and ensure A/B↔names and rally_id
     formats match existing reels conventions (the models are vendored from reels, preserving consistency).
   - Write rallies from RallySeg.csv; determine has_video/video_filename by scanning rally_video/*.mp4 (**only some rallies have files**).
   - Write shots by flattening label/set{1,2,3}.csv; see the DDL for column mapping.
3. Use transactions and INSERT OR REPLACE for idempotent reruns; detect matches with local data automatically.
4. CLI: `python mcps/badminton-db/ingest.py --db $BADMINTON_DB [--catalog-only] [--only <folder>]`. To expand to all 27/32 matches later, add HF downloading (requires only HF_TOKEN).

**A/B ↔ name mapping**: use ingest.py:derive_ab (A = the first player name in the folder name, matched case/underscore-insensitively), not DataLoader._extract_players (which returns top/bottom court players for the first rally and flips across games).

> Columns and values were verified against the one fully downloaded local Axelsen vs Lee match (1,213 shots, A=Viktor AXELSEN, B=LEE Zii Jia). Recompute ground truth with mcps/badminton-db/scripts/ground_truth.py (using exactly matches=all 32, shots=1 local match). After decoupling, mcps/badminton-db/scripts/test_decouple_parity.py also verifies that vendored and original reels parsers agree (parity OK).

---

### 3.3 DB access (local badminton-db MCP + badminton-db skill playbook)

Decision (the mainstream 2026 hybrid): expose DB access as a **streamable HTTP MCP in its own container** (typed tools with safeguards → deterministic, auditable access; nanobot connects to http://badminton-db:8801/mcp). **Skills are playbooks only** (triggers, enums, A/B, examples, tool selection), not access mechanisms. reels also uses MCP: both are in the connection layer; skills are in the behavior layer.

#### 3.3.1 badminton-db MCP server (own container, streamable HTTP)
Expose three tools:

| Tool | Input | Output | Purpose |
|------|------|------|------|
| list_tables | — | Table names | Let the agent explore structure |
| describe_table | table | Columns/types | Avoid putting the entire schema in the prompt |
| query | sql (single SELECT) | {rows, row_count} | Actual queries; SELECT-only + mode=ro |

Server skeleton (FastMCP, serving streamable HTTP at :8801/mcp by default, plus GET /healthz;
built-in SELECT-only safeguards). Set MCP_TRANSPORT=stdio to use stdio for smoke tests:
```python
#!/usr/bin/env python3
# mcps/badminton-db/server.py —— streamable-HTTP MCP：list_tables / describe_table / query(SELECT-only)
import os, re, sqlite3
from starlette.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

# Host/port injected through env (0.0.0.0:8801 in containers; MCP_HOST=127.0.0.1 for host/dev)
mcp = FastMCP("badminton-db",
              host=os.environ.get("MCP_HOST", "0.0.0.0"),
              port=int(os.environ.get("MCP_PORT", "8801")))

def _ro():
    db = sqlite3.connect(f"file:{os.environ['BADMINTON_DB']}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db

@mcp.tool()
def list_tables() -> list[str]:
    with _ro() as db:
        return [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")]

@mcp.tool()
def describe_table(table: str) -> list[dict]:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        return [{"error": "bad table name"}]
    with _ro() as db:
        return [dict(r) for r in db.execute(f"PRAGMA table_info({table})")]

@mcp.tool()
def query(sql: str) -> dict:
    """Accept only a single SELECT; return {rows, row_count} (up to 200 rows)."""
    if not re.match(r"^\s*select\b", sql, re.I) or ";" in sql.rstrip().rstrip(";"):
        return {"error": "only a single SELECT is allowed"}
    with _ro() as db:
        try:
            rows = [dict(r) for r in db.execute(sql).fetchmany(200)]
            return {"rows": rows, "row_count": len(rows)}
        except Exception as e:
            return {"error": str(e)}

# For compose healthcheck / depends_on: service_healthy
@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_req):
    return JSONResponse({"ok": True})

if __name__ == "__main__":
    if os.environ.get("MCP_TRANSPORT") == "stdio":
        mcp.run()                              # stdio（smoke test）
    else:
        mcp.run(transport="streamable-http")   # Default: HTTP at :8801/mcp
```
- Security: mode=ro + SELECT-only query provide two layers; **the MCP server is the security boundary**, not exec/CLI.
  The endpoint is **compose-network-only** (http://badminton-db:8801/mcp), without auth; never publish its port or tunnel it.
- Container: mcps/badminton-db/Dockerfile (image badmintongpt-db:0.1.0, compose service badminton-db),
  with data/badminton.db mounted as a volume; /healthz feeds the compose healthcheck, and gateway uses
  `depends_on: { badminton-db: { condition: service_healthy } }` to wait for readiness.
- Registration: see mcpServers.badminton-db in §3.1.1 (type:streamableHttp + url).

#### 3.3.2 badminton-db skill (playbook, not access mechanism)
The skill contains only domain knowledge on effective use, directing the agent to the MCP tools above when triggered.

```
${BADMINTONGPT_HOME}/skills/badminton-db/
├── SKILL.md
└── references/
    └── schema.md     # Enum values, A/B↔names, rally_id/has_video rules, example SQL
```

`SKILL.md`：
```markdown
---
name: badminton-db
description: Query the badminton match database (a player's matches, shot-by-shot counts and reasons
  for winning/losing points, scores, and tactical rally clips). For existing match data questions,
  consult this playbook before calling badminton-db MCP tools.
---

# How to query
1. Use describe_table to inspect columns when needed; fetch data with a **single SELECT** through query.
2. Rally clips: always use `WHERE has_video=1` in query and return only rallies with actual videos.
3. Chinese enums for shot types/reasons for winning or losing points, A/B↔names, and rally_id format → see references/schema.md.

# Common queries
- A player's matches: query("SELECT name FROM matches WHERE name LIKE '%AXELSEN%'")
- Shot-type points: query("SELECT COUNT(*) FROM shots WHERE type='殺球' AND player='A' AND win_reason<>''")
- Lost-point reasons: query("SELECT lose_reason, COUNT(*) n FROM shots WHERE lose_reason<>'' GROUP BY 1 ORDER BY n DESC")
```

`references/schema.md` (enum/mapping reference, loaded only after triggering):
```
matches(folder, name, tournament, round, player_a, player_b, year, is_practice)
rallies(match_folder, rally_id, set_no, score_a, score_b, start_frame, end_frame, has_video, video_filename)
shots(match_folder, set_no, rally, ball_round, player /*A|B*/, server, type /*shot type*/,
      aroundhead, backhand, hit_area, landing_area, lose_reason, win_reason,
      getpoint_player /*A|B*/, roundscore_a, roundscore_b, ...)

Shot type (type): 放小球,挑球,擋小球,殺球,點扣,發短球,推球,切球,過度切球,勾球,
                 長球,發長球,平球,撲球,後場抽平球,防守回抽,防守回挑,未知球種
lose_reason: 出界,對手落地致勝,未過網,掛網,落點判斷失誤
win_reason: 對手出界,落地致勝,對手未過網,對手掛網,對手落點判斷失誤
player/getpoint_player: A / B (names in matches.player_a/player_b)
rally_id: set_scoreA_scoreB (e.g. 1_05_04), corresponding to rally_video filenames; clip queries require has_video=1.
```

#### 3.3.3 Why this separation
- **Access through MCP**: query/list_tables/describe_table are typed tools → **deterministic, auditable access**; the harness sees tool names directly (§7).
- **Skills as playbooks**: progressively disclose domain knowledge such as enums, examples, and has_video rules, saving context and supporting modularity (future charts/tactic-clips use the same pattern).
- **No exec needed**: DB access no longer uses a CLI; skills have no scripts to run. **Even if a skill does not trigger, the agent can call badminton-db MCP tools directly** (always available), making this more robust than a skills-only approach.

#### 3.3.4 Notes
- query accepts only a single SELECT with mode=ro; describe_table validates table names against an allowlist regex.
- Verify skill discovery paths (workspace skills/ vs ~/.nanobot/skills/) for the nanobot version; see §8.

#### 3.3.5 Alternatives
- **Typed-only (stricter)**: remove query and expose only predefined typed tools such as list_matches(player?), shot_stats(match, group_by), and find_rallies(match, type, has_video), preventing agent-written SQL entirely (most deterministic, but less flexible for statistics and requires tool design in advance).
- **Hybrid**: typed tools cover common questions, with query retained as fallback.

---

### 3.4 reels（remote MCP + `badminton-reels` skill playbook）

reels MCP is an **existing remote service (unchanged)**, paired with a local **badminton-reels skill** playbook, symmetrically with badminton-db.

Connection: see reels_mcp_usage.md (remote HTTP, CF Access service token). Tool contract (from REELS_MCP_HANDOFF.md):

| Tool | Input | Output |
|------|------|------|
| `generate_reel` | `match_name` (+ `style/duration_target_sec/focus_player/shot_types/sets/rally_ids/max_highlights/narrative_emphasis/voice_id/enable_anchor/language`) | `{job_id, state}` |
| `get_reel_status` | `job_id` | `{state, stage, total_stages, message, error}` |
| `get_reel_result` | `job_id` | `{ready, video_url, selected_rally_ids, duration_sec, quality_score, style, language, script_summary}` |

`state ∈ {queued, running, succeeded, failed}`。

**Asynchronous interaction** (encapsulated in the badminton-reels playbook; see §3.4.1):
1. `generate_reel(...)` → obtain job_id and immediately tell the user "Generating the video (a few minutes)."
2. Call `get_reel_status(job_id)` periodically until succeeded/failed.
3. Success → obtain and present video_url with get_reel_result(job_id); failure → report error.

**Video playback**: ✅ video_url is confirmed to be **directly playable in browsers** without a service token. After obtaining it, the agent can return a link or embedded video; **no backend proxy or signed URL is needed**.

#### 3.4.1 `badminton-reels` skill（playbook）
Do not change reels MCP; only add a local skill to progressively disclose asynchronous orchestration and conventions.

```
${BADMINTONGPT_HOME}/skills/badminton-reels/
└── SKILL.md
```

`SKILL.md`：
```markdown
---
name: badminton-reels
description: Generate match highlight videos. When the user wants to make a highlight video,
  follow this playbook to call badminton-reels MCP tools (asynchronous, taking a few minutes).
---

# Procedure (asynchronous)
1. generate_reel(match_name, style?, ...) → {job_id, state}; immediately tell the user "Generating (a few minutes)."
2. Call get_reel_status(job_id) periodically until state=succeeded / failed.
3. succeeded → get_reel_result(job_id) for video_url, embed/link directly; failed → report error.

# Conventions
- Always pass matches.name as match_name (folder name without .mp4; use badminton-db to look up/confirm it first).
- video_url plays directly in the browser without additional processing.
- Optional parameters: style / duration_target_sec / focus_player / shot_types / sets / rally_ids /
  max_highlights / narrative_emphasis / voice_id / enable_anchor / language (see contract table above).
- `language` (`zh-TW`|`en`, narration/voice/subtitles) is auto-filled by the gateway from the WebUI
  language picker (the fork's `mcp.py` injects it when the model omits it) — pass it only on an explicit request.
```

> reels tools are typed MCP tools with deterministic routing; the skill only explains their orchestration. Even if the skill does not trigger, the agent can call MCP tools directly.

---

### 3.5 Web Search
Enable tools.web.enable=true; duckduckgo is the default and needs no key. For higher quality, switch to tavily/brave with apiKey. Use for information absent from the DB: latest player rankings, updates, match news, etc.

### 3.6 Web UI
- Enable channels.websocket {enabled:true, port:8765}, start with nanobot gateway, and open http://127.0.0.1:8765.
- First verify conversation and tool calls using the built-in UI; present videos as video_url links/embeds per §3.4.

---

## 4. Key data flows (sequence)

**Flow A — Statistical query (text-to-SQL)**
```
User → Agent: "How many points did Axelsen win with smashes?"
Agent: (consult badminton-db skill playbook: enums/A-B/examples)
Agent → badminton-db MCP: query("SELECT COUNT(*) ... WHERE type='殺球' AND player='A' AND win_reason<>''")
MCP → Agent: {"rows":[{"n":10}], "row_count":1}
Agent → User: "10 smash winners." (optionally include SQL)
```

**Flow B — Tactical clips**
```
User → Agent: "Find rally clips of Lee's net shots in this match"
Agent → badminton-db MCP: query("SELECT DISTINCT rally_id, video_filename FROM rallies r JOIN shots s …
              WHERE s.type='放小球' AND s.player='B' AND r.has_video=1")
MCP → Agent: rows (with video)
Agent → User: list rallies + clips (note: many annotations, few actual files)
```

**Flow C — Highlight generation (asynchronous, across MCPs)**
```
User → Agent: "Make highlights of this match"
Agent → reels.generate_reel(match_name, style=…) → {job_id, queued}
Agent → User: "Generating…"
loop: Agent → reels.get_reel_status(job_id) → running/…/succeeded
Agent → reels.get_reel_result(job_id) → {video_url}
Agent → User: video link/embed
```

**Flow D — External information**
```
User → Agent: "What is Axelsen's latest world ranking?"
Agent → web.search(...) → web.fetch(...) → Agent → User (with sources)
```

---

## 5. Security and deployment
- **reels MCP**: Cloudflare Tunnel + Access service token (credentials in env, not committed).
- **DB (badminton-db MCP)**: single-SELECT query + mode=ro; the agent can never write. Own container, streamable HTTP **on the compose network only** (badminton-db:8801, no host publishing or tunnel).
- **Secrets**: inject all through `${ENV}` (OpenAI key, CF Access token); load through systemd EnvironmentFile= or direnv.
- **Deployment**: one container per MCP—gateway (nanobot + embedded stdio util), badminton-db (HTTP, mounted read-only badminton.db), cloudflared; reels is remote. Skill playbooks remain with gateway.
- Note: moving DB access to MCP **removes the need for exec**, reducing the attack surface.

---

## 6. Implementation steps (how to write it, recommended order)

1. **DB ingestion**（§3.2）
   - Write mcps/badminton-db/ingest.py using vendored ingest_lib/ (no badminton-reels dependency; only HF_TOKEN).
   - Scope: matches=all 32 catalog entries (no downloads), rallies/shots=1 local match.
   - Produce badminton.db; verify values with queries from mcps/badminton-db/scripts/ground_truth.py (smash winners=10, out of bounds=50, lifts 116/86…).
2. **`badminton-db` MCP + skill playbook**（§3.3）
   - Write mcps/badminton-db/server.py (FastMCP streamable-http, :8801/mcp + /healthz; list_tables/describe_table/query SELECT-only); set BADMINTON_DB and test locally (`MCP_TRANSPORT=stdio .venv/bin/python mcps/badminton-db/scripts/test_db_mcp.py`).
   - Create skills/badminton-db/: SKILL.md + references/schema.md (playbook, no scripts).
3. **nanobot configuration** (§3.1)
   - Fill ~/.nanobot/config.json (providers, websocket, tools.web, top-level mcpServers: local stdio badminton-db + remote badminton-reels).
   - Confirm tools from both MCPs are listed and nanobot discovers the badminton-db skill.
   - Load env, run nanobot gateway, and verify WebUI startup and web.search.
4. **System prompt (brief routing)** (§3.1.3)
   - Write only persona + routing hints (DB→badminton-db MCP/skill, video→reels, external→web); keep schema/enums in the skill.
   - Manually test a few Flow A/B questions: confirm DB questions call query with correct SQL.
5. **reels integration + skill playbook** (§3.4 / §3.4.1)
   - Create skills/badminton-reels/SKILL.md (asynchronous orchestration + conventions).
   - Run Flow C once (generate→status→result); confirm video_url plays directly in the browser.
6. **Acceptance harness** (§7)
   - Write eval/run_eval.py to run nine questions and compare tool calls and ground truth.
7. **Documentation**: update README (startup, env, ingest commands).

---

## 7. Testing and acceptance (Success Metric)

Use the nine questions in TASK.md (including ground truth). The harness checks **(1) expected tool calls** and **(2) correct response content**.

#### 7.1 Expected tool mapping (excerpt; full table in TASK.md)
| # | Question | Expected tool | Ground truth |
|---|------|---------|--------------|
| 1 | Axelsen's matches | badminton-db query(matches) | 6 matches |
| 2 | Points won with smashes | badminton-db query(shots) | 10 |
| 3 | Most common reason for losing points | badminton-db query(shots) | Out of bounds 50 |
| 4 | Compare lift counts | badminton-db query(shots) | A116 / B86 |
| 5 | Scores for three games | badminton-db query | 19–21,21–11,23–21 |
| 6 | Net-shot clips | badminton-db query(rallies has_video) | 183 annotations, only 8 files |
| 7 | Make Axelsen vs Lee highlights | reels.generate_reel→status→result | Playable video_url |
| 8 | World ranking trend | web.search | External |
| 9 | Years/levels | badminton-db query(matches) | All 2022; 27+5 |

> Q1/Q9 require all 32 matches catalog entries (§3.2.2); Q2–Q6 use shot-by-shot data for the one local match.

#### 7.2 Harness design (eval/run_eval.py)
- **Driver**: send prompts one by one through nanobot's websocket channel (ws://127.0.0.1:8765) and collect the event stream.
- **Capture tool calls**: enable channels.sendToolHints=true, parse tool/MCP names from events, and check against expected tools.
  - DB questions appear as **badminton-db MCP query** (typed, deterministic, easy to compare); reels questions use generate_reel, etc. Easier to capture than exec/CLI calls.
- **Check answers**: for SQL questions, independently run the corresponding SQL for ground truth and compare key numbers in the agent's answer; reels questions require a final video_url; web questions require search.
- **Output**: per-question tool_match: pass/fail and answer_match: pass/fail, plus overall pass rates.

```python
# Skeleton (adapt event protocol to actual nanobot WS format)
CASES = [
  {"q": "Which Axelsen matches are in the database?", "expect_tool": "query",   # badminton-db MCP
   "check": lambda ans: "6" in ans or ans.count("AXELSEN") >= 6},
  {"q": "Make a highlight video of the Axelsen vs Lee match", "expect_tool": "generate_reel",
   "check": lambda ans: "http" in ans},   # Playable video_url
  # …remaining seven questions
]
# for c in CASES: send(c["q"]); ev = collect(); assert c["expect_tool"] in tools(ev); assert c["check"](final_text(ev))
```

> ⚠️ Verify the nanobot WS event format first, including the tool-name field. If WS parsing is difficult, fall back to headless nanobot agent for individual questions and parse stdout/log tool hints.

---

## 8. Confirmed decisions (previous questions resolved)
1. ✅ **mcpServers format**: top-level mcpServers + type:http (connection verified in reels_mcp_usage.md, §3.1.1).
2. ✅ **Video playback**: video_url plays directly in the browser; embed/link it (§3.4).
3. ✅ **Default LLM**: OpenAI (both deep/fast; still switchable, §3.1.1).
4. ✅ **DB scope**: matches=all 32 catalog entries, rallies/shots=1 local match (§3.2.2).
5. ✅ **Access through MCP, behavior through one skill playbook per capability**:
   - DB = local badminton-db MCP (query/list_tables/describe_table, SELECT-only) + badminton-db skill (§3.3); **no more exec**.
   - reels = remote badminton-reels MCP + badminton-reels skill (async orchestration/conventions, §3.4.1).
   - Move details (schema/enums, reels orchestration) from the system prompt to the respective skills.

## Implemented and verified (nanobot v0.2.1, 2026-06-06)
**Actual findings** for previously unverified items after implementation (these take precedence over conflicting examples above):
- **mcpServers location**: actually **tools.mcpServers**, not top-level. Remote uses type:"streamableHttp" + url + headers; local uses type:"stdio" + command/args/env.
- **Skill discovery path**: **~/.nanobot/workspace/skills/** (symlinked to this project's skills/).
- **System prompt location**: **~/.nanobot/workspace/SOUL.md** (no systemPrompt configuration key); routing hints and DB quick-reference rules go here.
- **Model settings**: agents.defaults.model="gpt-5.1" (**bare name**, no openai/ prefix), provider="openai", providers.openai.apiKey="${OPENAI_API_KEY}" (nanobot supports ${VAR}).
- **WS / WebUI**: channels.websocket{enabled:true,port:8765,websocketRequiresToken:false}; after nanobot gateway, WebUI is at ws://127.0.0.1:8765 (health at :18790).
- **Acceptance driver**: headless nanobot agent -m with parsed ↳ tool hints (sendToolHints:true); WS is not used.
- **Important schema correction**: rallies/shots join key changed to **match_name (= matches.name, without .mp4)**; including .mp4 previously returned zero rows when the agent scoped by readable names.
- **Results**: mcps/badminton-db/scripts/verify_db.py 23/23; nine-question e2e tool routing 8/8 and answers 8/8 (DB/web); reels generate_reel routes correctly and returns job_id.
- **Independent MCPs (container refactoring, verified)**: this repo's own MCPs moved into mcps/, each independent.
  - badminton-db = **separate container** (mcps/badminton-db/Dockerfile, image badmintongpt-db:0.1.0,
    compose service badminton-db), now serving **streamable HTTP** on the compose network at
    http://badminton-db:8801/mcp (no auth, never public) + GET /healthz; nanobot connects with
    `{"type":"streamableHttp","url":"http://badminton-db:8801/mcp","enabledTools":[...]}`. Only
    MCP_TRANSPORT=stdio selects stdio (smoke tests). Host/dev: `MCP_HOST=127.0.0.1 python mcps/badminton-db/server.py`.
  - util (sleep) = **unchanged transport**, still **stdio**, launched in-process by gateway (`{"type":"stdio",
    "command":"python3","args":["/app/mcps/util/server.py"],"enabledTools":["sleep"],"toolTimeout":70}`），
    **not a separate container**.
  - reels = **unchanged**, still remote streamableHttp (https://reels-mcp.nycu-adsl.cc/mcp,
    CF-Access-Client-Id/Secret = `${REELS_CF_CLIENT_ID}/${REELS_CF_CLIENT_SECRET}`); this repo does not containerize it.
  - **Gateway becomes a pure host**: Dockerfile no longer copies db_mcp/ / ingest.py / scripts/; it copies mcps/util/ instead.
    Gateway no longer sets BADMINTON_DB and uses `depends_on: { badminton-db: { condition: service_healthy } }`;
    entrypoint no longer warns about missing DB files. cloudflared/tunnel is unchanged (gateway only; DB stays internal).
  - **Ingest decoupled from reels**: ingest.py no longer injects $REELS_SRC or imports badminton.*; it uses vendored
    mcps/badminton-db/ingest_lib/ (RallySegment/ShotLabel + parse.extract_tournament_round + thin HF
    DataLoader). DB building requires only HF_TOKEN. REELS_SRC/REELS_SRC_HOST were removed from .env.example and
    compose ingest. One-time build: `docker compose --profile ingest run --rm ingest` (badmintongpt-db image).
  - Compose services are now gateway, badminton-db, cloudflared, and ingest (profile).
  - **Verification**: health-ordered depends_on startup works; gateway logs show MCP server 'badminton-db': connected (HTTP)
    and util connected (stdio); list_tables/query work over HTTP and DELETE is rejected; verify_db 23/23,
    parity OK; decoupled ingest for Axelsen vs Lee yields **1,213 shots** (A=Viktor AXELSEN, B=LEE Zii Jia).
  - example-mcp-server/ is a **standalone documentation deliverable** (REMOTE_MCP_SERVER_GUIDE.md example), **not moved into mcps/**;
    server.py already runs streamable-http (env MCP_HOST/MCP_PORT/PUBLIC_BASE_URL/OUTPUT_DIR); containerization needs no code changes.
```
